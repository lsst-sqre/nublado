"""Service to manage user lab environments."""

from __future__ import annotations

import json
import re
from copy import copy
from functools import partial
from pathlib import Path
from typing import Optional

from kubernetes_asyncio.client import (
    V1ConfigMapEnvSource,
    V1ConfigMapVolumeSource,
    V1Container,
    V1ContainerPort,
    V1DownwardAPIVolumeFile,
    V1DownwardAPIVolumeSource,
    V1EmptyDirVolumeSource,
    V1EnvFromSource,
    V1EnvVar,
    V1EnvVarSource,
    V1KeyToPath,
    V1LocalObjectReference,
    V1ObjectFieldSelector,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceFieldSelector,
    V1ResourceRequirements,
    V1SecretKeySelector,
    V1SecretVolumeSource,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import LabConfig, PVCVolumeSource, UserHomeDirectorySchema
from ..constants import LAB_STOP_GRACE_PERIOD
from ..models.domain.docker import DockerReference
from ..models.domain.gafaelfawr import GafaelfawrUser, GafaelfawrUserInfo
from ..models.domain.lab import LabVolumeContainer
from ..models.domain.rspimage import RSPImage
from ..models.v1.lab import (
    LabResources,
    LabSpecification,
    LabStatus,
    ResourceQuantity,
    UserLabState,
)
from ..storage.k8s import K8sStorageClient
from ..util import deslashify
from .builder import LabBuilder
from .image import ImageService
from .size import SizeManager
from .state import LabStateManager

__all__ = ["LabManager"]


class LabManager:
    def __init__(
        self,
        *,
        manager_namespace: str,
        instance_url: str,
        lab_state: LabStateManager,
        lab_builder: LabBuilder,
        size_manager: SizeManager,
        image_service: ImageService,
        logger: BoundLogger,
        lab_config: LabConfig,
        k8s_client: K8sStorageClient,
        slack_client: Optional[SlackWebhookClient] = None,
    ) -> None:
        self.manager_namespace = manager_namespace
        self.instance_url = instance_url
        self._lab_state = lab_state
        self._builder = lab_builder
        self._size_manager = size_manager
        self._image_service = image_service
        self._logger = logger
        self.lab_config = lab_config
        self.k8s_client = k8s_client
        self._slack_client = slack_client

    async def create_lab(
        self, user: GafaelfawrUser, lab: LabSpecification
    ) -> None:
        """Schedules creation of user lab objects/resources.

        Parameters
        ----------
        user
            User for whom the lab is being created.
        lab
            Specification for lab to spawn.

        Raises
        ------
        InvalidDockerReferenceError
            Raised if the Docker image reference in the lab specification is
            invalid.
        LabExistsError
            Raised if this user already has a lab.
        """
        selection = lab.options.image_list or lab.options.image_dropdown
        if selection:
            reference = DockerReference.from_str(selection)
            image = await self._image_service.image_for_reference(reference)
        elif lab.options.image_class:
            image_class = lab.options.image_class
            image = self._image_service.image_for_class(image_class)
        elif lab.options.image_tag:
            tag = lab.options.image_tag
            image = await self._image_service.image_for_tag_name(tag)

        # Check to see if the lab already exists. If so, but it is in a failed
        # state, delete it first.
        status = await self._lab_state.get_lab_status(user.username)
        delete_first = status == LabStatus.FAILED

        # Start the spawning process. This also checks for conflicts and
        # raises an exception if the lab already exists and is not in a failed
        # state.
        #
        # A LabManager is per-request, so the management of the background
        # task that does the lab spawning (which outlasts the request that
        # kicks it off) is handed off to LabStateManager here.
        resources = self._size_manager.resources(lab.options.size)
        await self._lab_state.start_lab(
            username=user.username,
            state=UserLabState.from_request(user, lab, resources),
            spawner=partial(
                self._spawn_lab,
                user=user,
                lab=lab,
                image=image,
                delete_first=delete_first,
            ),
            start_progress=35,
            end_progress=75,
        )

    def _get_homedir(self, user: GafaelfawrUserInfo) -> str:
        match self.lab_config.homedir_schema:
            case UserHomeDirectorySchema.USERNAME:
                return f"/home/{user.username}"
            case UserHomeDirectorySchema.INITIAL_THEN_USERNAME:
                return f"/home/{user.username[0]}/{user.username}"

    async def _spawn_lab(
        self,
        *,
        user: GafaelfawrUser,
        lab: LabSpecification,
        image: RSPImage,
        delete_first: bool,
    ) -> str:
        """Do the work of creating a user's lab.

        This method is responsible for creating the Kubernetes objects and
        telling Kubernetes to start the user's pod. It does not wait for the
        pod to finish starting. It is run within a background task managed by
        `~jupyterlabcontroller.services.state.LabStateManager`, which then
        waits for the lab to start and updates internal state as appropriate.

        Parameters
        ----------
        user
            Identity information for the user spawning the lab.
        lab
            Specification for the lab environment to create.
        image
            Docker image to run as the lab.
        delete_first
            Whether there is an existing lab that needs to be deleted first.

        Returns
        -------
        str
            Cluster-internal URL at which the lab will be listening once it
            has finished starting.
        """
        username = user.username

        # Delete an existing failed lab first if needed.
        if delete_first:
            self._logger.info("Deleting existing failed lab")
            await self._lab_state.publish_event(
                username, f"Deleting existing failed lab for {username}", 2
            )
            await self._delete_lab_and_namespace(username, 3, 9)

        # This process has three stages. First, create the user's namespace.
        self._logger.info("Creating new lab")
        await self.create_namespace(user)
        await self._lab_state.publish_event(
            username, "Created user namespace", 10
        )

        # Second, create all the supporting resources the lab pod will need.
        await self.create_secrets(user)
        await self.create_pvcs(user)
        await self.create_nss(user)
        await self.create_file_configmap(user)
        await self.create_env(user, lab, image)
        await self.create_network_policy(user)
        await self.create_quota(user)
        await self.create_lab_service(user)
        await self._lab_state.publish_event(
            username, "Created Kubernetes resources for lab", 25
        )

        # Finally, create the lab pod.
        resources = self._size_manager.resources(lab.options.size)
        await self.create_user_pod(user, resources, image)
        await self._lab_state.publish_pod_creation(
            username, "Requested lab Kubernetes pod", 30
        )

        # Return the URL where the lab will be listening after it starts.
        return self._builder.build_internal_url(user.username, lab.env)

    async def create_namespace(self, user: GafaelfawrUser) -> None:
        """Create the namespace for a user's lab environment.

        Parameters
        ----------
        username
            Username for which to create a namespace.

        Raises
        ------
        KubernetesError
            Raised if the Kubernetes API call fails.
        """
        namespace = self._builder.namespace_for_user(user.username)
        await self.k8s_client.create_user_namespace(namespace)

    async def create_secrets(self, user: GafaelfawrUser) -> None:
        """Create the secrets for the user's lab environment.

        There will at least be a secret with the user's token and any
        additional secrets specified in the lab configuration, and there may
        also be a Docker pull secret.

        Parameters
        ----------
        user
            User for which to create secrets.
        token
            User's notebook token.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        MissingSecretError
            Raised if one of the specified source secrets could not be found
            in Kubernetes.
        """
        namespace = self._builder.namespace_for_user(user.username)
        await self.k8s_client.create_secrets(
            secret_list=self.lab_config.secrets,
            username=user.username,
            token=user.token,
            source_ns=self.manager_namespace,
            target_ns=namespace,
        )
        if self.lab_config.pull_secret:
            await self.k8s_client.copy_secret(
                source_namespace=self.manager_namespace,
                source_secret=self.lab_config.pull_secret,
                target_namespace=namespace,
                target_secret="pull-secret",
            )

    #
    # We are splitting "build": create the in-memory object representing
    # the resource -- and "create": submit it to Kubernetes -- for the next
    # few things, so that we can more easily unit test the object construction
    # logic.
    #

    async def create_pvcs(self, user: GafaelfawrUserInfo) -> None:
        namespace = self._builder.namespace_for_user(user.username)
        pvcs = self.build_pvcs(user.username)
        if pvcs:
            await self.k8s_client.create_pvcs(pvcs, namespace)

    def build_pvcs(self, username: str) -> list[V1PersistentVolumeClaim]:
        pvcs: list[V1PersistentVolumeClaim] = []
        for volume in self.lab_config.volumes:
            if not isinstance(volume.source, PVCVolumeSource):
                continue
            name = f"{username}-nb-pvc-{len(pvcs) + 1}"
            pvc = V1PersistentVolumeClaim(
                metadata=V1ObjectMeta(name=name),
                spec=V1PersistentVolumeClaimSpec(
                    storage_class_name=volume.source.storage_class_name,
                    access_modes=volume.source.access_modes,
                    resources=V1ResourceRequirements(
                        requests=volume.source.resources.requests
                    ),
                ),
            )
            pvcs.append(pvc)
        return pvcs

    async def create_nss(self, user: GafaelfawrUserInfo) -> None:
        namespace = self._builder.namespace_for_user(user.username)
        data = self.build_nss(user=user)
        await self.k8s_client.create_configmap(
            name=f"{user.username}-nb-nss",
            namespace=namespace,
            data=data,
        )

    def build_nss(self, user: GafaelfawrUserInfo) -> dict[str, str]:
        """Construct the NSS ``ConfigMap`` to mount in the lab container.

        The NSS ``ConfigMap`` provides the ``/etc/passwd`` and ``/etc/group``
        files for the running lab. These files are constructed by adding
        entries for the user and their groups to a base file in the Nublado
        controller configuration.

        Parameters
        ----------
        user
            User metadata.

        Returns
        -------
        dict of str to str
            Contents of the ``ConfigMap``.
        """
        etc_passwd = self.lab_config.files["/etc/passwd"].contents
        etc_group = self.lab_config.files["/etc/group"].contents

        # Construct the user's /etc/passwd entry. Different sites use
        # different schemes for constructing the home directory path.
        homedir = self._get_homedir(user)
        etc_passwd += (
            f"{user.username}:x:{user.uid}:{user.gid}:"
            f"{user.name}:{homedir}:/bin/bash\n"
        )

        # Construct the /etc/group entry by adding all groups that have GIDs.
        # Add the user as an additional member of their supplemental groups.
        # We can't do anything with groups that don't have GIDs, so ignore
        # those.
        for group in user.groups:
            if not group.id:
                continue
            if group.id == user.gid:
                etc_group += f"{group.name}:x:{group.id}:\n"
            else:
                etc_group += f"{group.name}:x:{group.id}:{user.username}\n"

        # Return the results in a form suitable for the data member of a
        # ConfigMap object.
        return {"/etc/passwd": etc_passwd, "/etc/group": etc_group}

    async def create_file_configmap(self, user: GafaelfawrUserInfo) -> None:
        namespace = self._builder.namespace_for_user(user.username)
        data = self.build_file_configmap()
        await self.k8s_client.create_configmap(
            name=f"{user.username}-nb-configmap",
            namespace=namespace,
            data=data,
        )

    def build_file_configmap(self) -> dict[str, str]:
        files = self.lab_config.files
        data = {}
        for file in files:
            if not files[file].modify:
                data[file] = files[file].contents
            else:
                # We don't currently have anything other than passwd/group
                # which are handled specially anyway (in NSS).
                #
                # We might have to add other file handling here later.
                pass
        return data

    async def create_env(
        self,
        user: GafaelfawrUserInfo,
        lab: LabSpecification,
        image: RSPImage,
    ) -> None:
        data = self.build_env(user, lab, image)
        await self.k8s_client.create_configmap(
            name=f"{user.username}-nb-env",
            namespace=self._builder.namespace_for_user(user.username),
            data=data,
        )

    def build_env(
        self,
        user: GafaelfawrUserInfo,
        lab: LabSpecification,
        image: RSPImage,
    ) -> dict[str, str]:
        """Construct the environment for the user's lab pod.

        Parameters
        ----------
        user
            User identity information.
        lab
            Specification for the lab, received from JupyterHub or the user
            themselves.
        image
            Image to spawn.
        token
            User's Gafaelfawr token.

        Returns
        -------
        dict of str to str
            User's lab environment, which will be stored in a ``ConfigMap``
            and projected into their lab pod.
        """
        env = copy(lab.env)

        # Add additional environment variables based on user options.
        if lab.options.enable_debug:
            env["DEBUG"] = "TRUE"
        if lab.options.reset_user_env:
            env["RESET_USER_ENV"] = "TRUE"

        # Add standard environment variables.
        resources = self._size_manager.resources(lab.options.size)
        size_str = [
            x.description
            for x in self._size_manager.formdata()
            if x.name == lab.options.size.value.title()
        ][0]
        env.update(
            {
                # We would like to deprecate this, following KubeSpawner, but
                # it's currently used by the lab extensions and by mobu.
                "JUPYTER_IMAGE": image.reference_with_digest,
                # Image data for display frame
                "JUPYTER_IMAGE_SPEC": image.reference_with_digest,
                "IMAGE_DESCRIPTION": image.display_name,
                "IMAGE_DIGEST": image.digest,
                # Container data for display frame
                "CONTAINER_SIZE": size_str,
                # Normally set by JupyterHub so keep compatibility
                "CPU_GUARANTEE": str(resources.requests.cpu),
                "CPU_LIMIT": str(resources.limits.cpu),
                "MEM_GUARANTEE": str(resources.requests.memory),
                "MEM_LIMIT": str(resources.limits.memory),
                # Get global instance URL
                "EXTERNAL_INSTANCE_URL": self.instance_url,
            }
        )

        # Finally, add any environment variable settings from our
        # configuration. Anything set here overrides anything the user sends
        # or anything we add internally.
        env.update(self.lab_config.env)

        return env

    async def create_network_policy(self, user: GafaelfawrUserInfo) -> None:
        # No corresponding "build" because the policy is hardcoded in the
        # storage driver.
        await self.k8s_client.create_network_policy(
            name=f"{user.username}-nb-env",
            namespace=self._builder.namespace_for_user(user.username),
        )

    async def create_lab_service(self, user: GafaelfawrUserInfo) -> None:
        # No corresponding build because the service is hardcoded in the
        # storage driver.
        await self.k8s_client.create_lab_service(
            username=user.username,
            namespace=self._builder.namespace_for_user(user.username),
        )

    async def create_quota(self, user: GafaelfawrUserInfo) -> None:
        if not user.quota or not user.quota.notebook:
            return
        await self.k8s_client.create_quota(
            f"{user.username}-nb",
            self._builder.namespace_for_user(user.username),
            ResourceQuantity(
                cpu=user.quota.notebook.cpu,
                memory=int(user.quota.notebook.memory * 1024 * 1024 * 1024),
            ),
        )

    async def create_user_pod(
        self,
        user: GafaelfawrUserInfo,
        resources: LabResources,
        image: RSPImage,
    ) -> None:
        pod_spec = self.build_pod_spec(user, resources, image)
        serialized_groups = json.dumps([g.dict() for g in user.groups if g.id])
        await self.k8s_client.create_pod(
            name=f"{user.username}-nb",
            namespace=self._builder.namespace_for_user(user.username),
            pod_spec=pod_spec,
            annotations={
                "nublado.lsst.io/user-name": user.name,
                "nublado.lsst.io/user-groups": serialized_groups,
            },
            username=user.username,
        )

    def build_cm_volumes(self, username: str) -> list[LabVolumeContainer]:
        #
        # Step three: other configmap files
        #
        vols = []
        for cfile in self.lab_config.files:
            dscfile = deslashify(cfile)
            cmname = f"{username}-nb-configmap"
            if cfile == "/etc/passwd" or cfile == "/etc/group":
                cmname = f"{username}-nb-nss"
            path = Path(cfile)
            bname = str(path.name)
            filename = re.sub(r"[_\.]", "-", str(path.name))
            vols.append(
                LabVolumeContainer(
                    volume=V1Volume(
                        name=f"nss-{username}-{filename}",
                        config_map=V1ConfigMapVolumeSource(
                            name=cmname,
                            items=[
                                V1KeyToPath(
                                    mode=0o0644,
                                    key=dscfile,
                                    path=bname,
                                )
                            ],
                        ),
                    ),
                    volume_mount=V1VolumeMount(
                        mount_path=cfile,
                        name=f"nss-{username}-{filename}",
                        read_only=True,  # Is that necessarily the case?
                        sub_path=bname,
                    ),
                )
            )
        return vols

    def build_secret_volume(self, username: str) -> LabVolumeContainer:
        #
        # Step four: secret
        #
        # All secrets are mounted in the same directory.  Secrets should
        # preferably be referred to by that path, although we also support
        # injecting them into environment variables and other paths for ease
        # of transition.
        sec_vol = LabVolumeContainer(
            volume=V1Volume(
                name=f"{username}-nb-secrets",
                secret=V1SecretVolumeSource(
                    secret_name=f"{username}-nb",
                ),
            ),
            volume_mount=V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/secrets",
                name=f"{username}-nb-secrets",
                read_only=True,
            ),
        )
        return sec_vol

    def build_extra_secret_volume_mounts(
        self, username: str
    ) -> list[V1VolumeMount]:
        """Build additional mounts of secrets into other paths.

        Parameters
        ----------
        username
            Username whose lab is being constructed.

        Returns
        -------
        list of V1VolumeMount
            Additional locations into which specific secrets are mounted.
        """
        mounts = []
        for spec in self.lab_config.secrets:
            if not spec.path:
                continue
            mount = V1VolumeMount(
                mount_path=spec.path,
                name=f"{username}-nb-secrets",
                read_only=True,
                sub_path=spec.secret_key,
            )
            mounts.append(mount)
        return mounts

    def build_env_volume(self, username: str) -> LabVolumeContainer:
        #
        # Step five: environment
        #
        env_vol = LabVolumeContainer(
            volume=V1Volume(
                name=f"{username}-nb-env",
                config_map=V1ConfigMapVolumeSource(
                    name=f"{username}-nb-env",
                ),
            ),
            volume_mount=V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/environment",
                name=f"{username}-nb-env",
                read_only=False,  # We'd like to be able to update this
            ),
        )
        return env_vol

    def build_tmp_volume(self) -> LabVolumeContainer:
        return LabVolumeContainer(
            volume=V1Volume(
                empty_dir=V1EmptyDirVolumeSource(),
                name="tmp",
            ),
            volume_mount=V1VolumeMount(
                mount_path="/tmp",
                read_only=False,
                name="tmp",
            ),
        )

    def build_runtime_volume(self, username: str) -> LabVolumeContainer:
        #
        # Step six: introspective information about the pod, only known
        # after pod dispatch.
        #

        # The only field we need is spec.nodeName
        # Except we can't have it:
        # https://github.com/kubernetes/kubernetes/issues/64168
        # So we will inject it into the env instead.
        # volfields = [
        #    "spec.nodeName",
        # ]
        resfields = [
            "limits.cpu",
            "requests.cpu",
            "limits.memory",
            "requests.memory",
        ]
        volfiles = []
        volfiles.extend(
            [
                V1DownwardAPIVolumeFile(
                    resource_field_ref=V1ResourceFieldSelector(
                        container_name="notebook",
                        resource=x,
                    ),
                    path=x.replace(".", "_").lower(),
                )
                for x in resfields
            ]
        )
        runtime_vol = LabVolumeContainer(
            volume=V1Volume(
                name=f"{username}-nb-runtime",
                downward_api=V1DownwardAPIVolumeSource(items=volfiles),
            ),
            volume_mount=V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/runtime",
                name=f"{username}-nb-runtime",
                read_only=True,
            ),
        )
        return runtime_vol

    def build_volumes(self, username: str) -> list[LabVolumeContainer]:
        """This stitches together the Volume and VolumeMount definitions
        from each of our sources.
        """
        # Begin with the /tmp empty_dir
        vols = []
        lab_config_vols = self._builder.build_lab_config_volumes(
            username, self.lab_config.volumes
        )
        vols.extend(lab_config_vols)
        cm_vols = self.build_cm_volumes(username=username)
        vols.extend(cm_vols)
        secret_vol = self.build_secret_volume(username=username)
        vols.append(secret_vol)
        env_vol = self.build_env_volume(username=username)
        vols.append(env_vol)
        tmp_vol = self.build_tmp_volume()
        vols.append(tmp_vol)
        runtime_vol = self.build_runtime_volume(username=username)
        vols.append(runtime_vol)
        return vols

    def build_init_containers(
        self, user: GafaelfawrUserInfo, resources: LabResources
    ) -> list[V1Container]:
        username = user.username
        init_ctrs = []
        ic_volumes = []
        for ic in self.lab_config.init_containers:
            if ic.volumes is not None:
                ic_volumes = self._builder.build_lab_config_volumes(
                    user.username, ic.volumes
                )
            ic_vol_mounts = [x.volume_mount for x in ic_volumes]
            if ic.privileged:
                ic_sec_ctx = V1SecurityContext(
                    run_as_non_root=False,
                    run_as_user=0,
                    allow_privilege_escalation=True,
                )
            else:
                ic_sec_ctx = V1SecurityContext(
                    run_as_non_root=True,
                    run_as_user=1000,
                    allow_privilege_escalation=False,
                )
            ctr = V1Container(
                name=ic.name,
                # We use the same environment as the notebook, because it
                # includes things we need for provisioning.
                env=[
                    V1EnvVar(name="EXTERNAL_GID", value=str(user.gid)),
                    V1EnvVar(name="EXTERNAL_UID", value=str(user.uid)),
                ],
                env_from=[
                    V1EnvFromSource(
                        config_map_ref=V1ConfigMapEnvSource(
                            name=f"{username}-nb-env"
                        )
                    ),
                ],
                image=ic.image,
                resources=V1ResourceRequirements(
                    limits={
                        "cpu": str(resources.limits.cpu),
                        "memory": str(resources.limits.memory),
                    },
                    requests={
                        "cpu": str(resources.requests.cpu),
                        "memory": str(resources.requests.memory),
                    },
                ),
                security_context=ic_sec_ctx,
                volume_mounts=ic_vol_mounts,
            )
            init_ctrs.append(ctr)
        return init_ctrs

    def build_pod_spec(
        self,
        user: GafaelfawrUserInfo,
        resources: LabResources,
        image: RSPImage,
    ) -> V1PodSpec:
        """Construct the pod specification for the user's lab pod.

        Parameters
        ----------
        user
            User identity information.
        resources
            User quota restrictions.
        image
            Image to spawn.

        Returns
        -------
        V1PodSpec
            Kubernetes pod specification for that user's lab pod.
        """
        volume_data = self.build_volumes(user.username)
        volumes = [v.volume for v in volume_data]
        mounts = [v.volume_mount for v in volume_data]
        mounts += self.build_extra_secret_volume_mounts(user.username)

        # Additional environment variables to set, apart from the ConfigMap.
        env = [
            V1EnvVar(
                name="ACCESS_TOKEN",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        key="token", name=f"{user.username}-nb", optional=False
                    )
                ),
            ),
            # spec.nodeName is not reflected in DownwardAPIVolumeSource:
            # https://github.com/kubernetes/kubernetes/issues/64168
            V1EnvVar(
                name="KUBERNETES_NODE_NAME",
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="spec.nodeName")
                ),
            ),
            # Deprecated, but what lsst.rsp 0.3.4 looks for.
            V1EnvVar(
                name="K8S_NODE_NAME",
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="spec.nodeName")
                ),
            ),
        ]
        for spec in self.lab_config.secrets:
            if not spec.env:
                continue
            env_var = V1EnvVar(
                name=spec.env,
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        key=spec.secret_key,
                        name=f"{user.username}-nb",
                        optional=False,
                    )
                ),
            )
            env.append(env_var)

        # Specification for the user's container.
        homedir = self._get_homedir(user)
        container = V1Container(
            name="notebook",
            args=["/opt/lsst/software/jupyterlab/runlab.sh"],
            env=env,
            env_from=[
                V1EnvFromSource(
                    config_map_ref=V1ConfigMapEnvSource(
                        name=f"{user.username}-nb-env"
                    )
                ),
            ],
            image=image.reference_with_digest,
            image_pull_policy="IfNotPresent",
            ports=[V1ContainerPort(container_port=8888, name="jupyterlab")],
            resources=V1ResourceRequirements(
                limits={
                    "cpu": str(resources.limits.cpu),
                    "memory": str(resources.limits.memory),
                },
                requests={
                    "cpu": str(resources.requests.cpu),
                    "memory": str(resources.requests.memory),
                },
            ),
            security_context=V1SecurityContext(
                run_as_non_root=True,
                run_as_user=user.uid,
                run_as_group=user.gid,
            ),
            volume_mounts=mounts,
            working_dir=homedir,
        )

        # Build the pod specification itself.
        # FIXME work out tolerations
        pull_secrets = None
        if self.lab_config.pull_secret:
            pull_secrets = [V1LocalObjectReference(name="pull-secret")]
        init_containers = self.build_init_containers(user, resources)
        pod = V1PodSpec(
            init_containers=init_containers,
            containers=[container],
            image_pull_secrets=pull_secrets,
            restart_policy="OnFailure",
            security_context=V1PodSecurityContext(
                run_as_non_root=True,
                fs_group=user.gid,
                supplemental_groups=[x.id for x in user.groups if x.id],
            ),
            volumes=volumes,
        )
        return pod

    async def delete_lab(self, username: str) -> None:
        """Delete the lab environment for the given user.

        Parameters
        ----------
        username
            Username whose environment should be deleted.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes error prevented lab deletion.
        UnknownUserError
            Raised if no lab currently exists for this user.
        """
        callback = partial(self._delete_lab_and_namespace, username, 25, 100)
        await self._lab_state.stop_lab(username, callback)

    async def _delete_lab_and_namespace(
        self, username: str, start_progress: int, end_progress: int
    ) -> None:
        """Delete the user's lab and namespace.

        Currently, this just deletes the namespace and lets that delete the
        pod. This results in an ungraceful shutdown, so in the future it will
        be changed to gracefully shut down the pod first and then delete the
        namespace.

        Parameters
        ----------
        username
            Username of lab to delete.
        start_progress
            Initial progress percentage.
        end_progress
            Final progress percentage.
        """
        pod = f"{username}-nb"
        namespace = self._builder.namespace_for_user(username)
        message = "Shutting down Kubernetes pod"
        await self._lab_state.publish_event(username, message, start_progress)
        await self.k8s_client.delete_pod(
            pod, namespace, grace_period=LAB_STOP_GRACE_PERIOD
        )
        message = "Deleting user namespace"
        progress = start_progress + int((end_progress - start_progress) / 2)
        await self._lab_state.publish_event(username, message, progress)
        await self.k8s_client.delete_namespace(namespace)
        await self.k8s_client.wait_for_namespace_deletion(namespace)
        message = f"Lab for {username} deleted"
        await self._lab_state.publish_event(username, message, end_progress)
        self._logger.info("Lab deleted")
