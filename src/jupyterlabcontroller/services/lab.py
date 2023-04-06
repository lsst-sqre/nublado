"""Service to manage user lab environments."""

from __future__ import annotations

import re
from asyncio import Task, create_task
from copy import copy, deepcopy
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
    V1HostPathVolumeSource,
    V1KeyToPath,
    V1LocalObjectReference,
    V1NFSVolumeSource,
    V1ObjectFieldSelector,
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
from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import FileMode, LabConfig, LabVolume
from ..exceptions import LabExistsError, UnknownUserError
from ..models.domain.docker import DockerReference
from ..models.domain.lab import LabVolumeContainer
from ..models.domain.rspimage import RSPImage
from ..models.domain.usermap import UserMap
from ..models.v1.event import Event, EventType
from ..models.v1.lab import (
    LabSpecification,
    LabStatus,
    PodState,
    UserData,
    UserInfo,
    UserResourceQuantum,
    UserResources,
)
from ..storage.k8s import K8sStorageClient
from ..util import deslashify
from .events import EventManager
from .image import ImageService
from .size import SizeManager

#  argh from aiojobs import Scheduler
#  blargh from ..constants import KUBERNETES_REQUEST_TIMEOUT


class LabManager:
    def __init__(
        self,
        *,
        manager_namespace: str,
        instance_url: str,
        user_map: UserMap,
        event_manager: EventManager,
        size_manager: SizeManager,
        image_service: ImageService,
        logger: BoundLogger,
        lab_config: LabConfig,
        k8s_client: K8sStorageClient,
        slack_client: Optional[SlackWebhookClient] = None,
    ) -> None:
        self.manager_namespace = manager_namespace
        self.instance_url = instance_url
        self.user_map = user_map
        self.event_manager = event_manager
        self._size_manager = size_manager
        self._image_service = image_service
        self.logger = logger
        self.lab_config = lab_config
        self.k8s_client = k8s_client
        self._slack_client = slack_client
        self._tasks: set[Task] = set()

    def namespace_from_user(self, user: UserInfo) -> str:
        """Exposed because the unit tests use it."""
        return f"{self.manager_namespace}-{user.username}"

    def check_for_user(self, username: str) -> bool:
        """True if there's a lab for the user, otherwise false."""
        r = self.user_map.get(username)
        return r is not None

    async def info_event(
        self, username: str, message: str, progress: int
    ) -> None:
        event = Event(message=message, progress=progress, type=EventType.INFO)
        self.event_manager.publish_event(username, event)
        msg = f"Spawning event: {message}"
        self.logger.debug(msg, progress=progress, user=username)

    async def completion_event(self, username: str, message: str) -> None:
        event = Event(message=message, type=EventType.COMPLETE)
        self.event_manager.publish_event(username, event)

    async def failure_event(
        self, username: str, message: str, fatal: bool = True
    ) -> None:
        event = Event(message=message, type=EventType.ERROR)
        self.event_manager.publish_event(username, event)
        self.logger.error(f"Spawning error: {message}", user=username)
        if fatal:
            event = Event(message="Lab creation failed", type=EventType.FAILED)
            self.event_manager.publish_event(username, event)
            self.logger.error("Lab creation failed", user=username)

    async def await_pod_spawn(self, namespace: str, username: str) -> None:
        """This is designed to run as a background task and just wait until
        the pod has been created and inject a completion event into the
        event queue when it has.
        """
        try:
            await self.k8s_client.wait_for_pod_creation(
                podname=f"nb-{username}", namespace=namespace
            )
        except Exception as e:
            self.logger.exception("Pod creation failed", user=username)
            await self.failure_event(username, str(e), fatal=True)
            self.user_map.set_status(username, status=LabStatus.FAILED)
            self.user_map.clear_internal_url(username)
        else:
            self.user_map.set_status(username, status=LabStatus.RUNNING)
            message = f"Lab Kubernetes pod started for {username}"
            await self.completion_event(username, message)
            self.logger.info("Lab pod started", user=username)

    async def await_ns_deletion(self, namespace: str, username: str) -> None:
        """This is designed to run as a background task and just wait until
        the pod has been created and inject a completion event into the
        event queue when it has.
        """
        try:
            await self.k8s_client.wait_for_namespace_deletion(namespace)
        except Exception as e:
            self.logger.exception("Namespace deletion failed", user=username)
            await self.failure_event(username, str(e), fatal=True)
            self.user_map.set_status(username, status=LabStatus.FAILED)
        else:
            await self.completion_event(username, "Lab deleted")
            self.user_map.remove(username)

    async def inject_pod_events(
        self,
        *,
        namespace: str,
        username: str,
        start_progress: int,
        end_progress: int,
    ) -> None:
        """This is designed to run as a background task.  When
        Kubernetes starts a pod, it will emit some events as the pod
        startup progresses.  This captures those events and injects them into
        the event queue.
        """
        progress = start_progress
        async for evt in self.k8s_client.reflect_pod_events(
            namespace=namespace, podname=f"nb-{username}"
        ):
            await self.info_event(username, evt, progress)
            # As with Kubespawner, we don't know how many of these we will
            # get, so we will just move 1/3 closer to the end of the
            # region each time.
            progress = int(progress + ((end_progress - progress) / 3))

    async def create_lab(
        self, user: UserInfo, token: str, lab: LabSpecification
    ) -> None:
        """Schedules creation of user lab objects/resources.

        Parameters
        ----------
        user
            User for whom the lab is being created.
        token
            Delegated notebook token for that user, which will be injected
            into the lab.
        lab
            Specification for lab to spawn.

        Raises
        ------
        InvalidDockerReferenceError
            Docker image reference in the lab specification is invalid.
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

        # unclear if we should clear the event queue before this.  Probably not
        # because we don't want to wipe out the existing log, since we will
        # not be spawning.
        if self.check_for_user(user.username):
            await self.failure_event(user.username, "Lab already exists")
            raise LabExistsError(f"Lab already exists for {user.username}")

        # Add a new usermap entry and clear the user event queue.
        self.user_map.set(
            user.username,
            UserData.new_from_user_resources(
                user=user,
                labspec=lab,
                resources=self._size_manager.resources(lab.options.size),
            ),
        )
        self.event_manager.reset_user(user.username)

        # This is all that we should do synchronously in response to the API
        # call. The rest should be done in the background, reporting status
        # through the event stream. Kick off the background job.
        await self.info_event(
            user.username, f"Starting lab creation for {user.username}", 2
        )
        pod_spawn_task = create_task(self._spawn_lab(user, token, lab, image))
        self._tasks.add(pod_spawn_task)
        pod_spawn_task.add_done_callback(self._tasks.discard)

    async def _spawn_lab(
        self,
        user: UserInfo,
        token: str,
        lab: LabSpecification,
        image: RSPImage,
    ) -> None:
        username = user.username
        namespace = self.namespace_from_user(user)

        # This process has three stages. First, create or recreate the user's
        # namespace. Second, create all the supporting resources the lab pod
        # will need. Finally, create the lab pod and wait for it to start,
        # reflecting any events back to the events API.
        try:
            await self.k8s_client.create_user_namespace(namespace)
            await self.info_event(username, "Created user namespace", 5)
            await self.create_user_lab_objects(
                user=user, lab=lab, image=image, token=token
            )
            await self.info_event(
                username, "Created Kubernetes resources for lab", 25
            )
            resources = self._size_manager.resources(lab.options.size)
            await self.create_user_pod(user, resources, image)
            self.user_map.set_pod_state(username, PodState.PRESENT)
            self.user_map.set_status(username, status=LabStatus.PENDING)
            await self.info_event(username, "Requested lab Kubernetes pod", 30)
        except Exception as e:
            msg = "Lab creation failed"
            self.logger.exception(msg, user=username)
            if self._slack_client:
                if isinstance(e, SlackException):
                    e.user = username
                    await self._slack_client.post_exception(e)
                else:
                    await self._slack_client.post_uncaught_exception(e)
            await self.failure_event(username, str(e), fatal=True)
            self.user_map.set_status(username, status=LabStatus.FAILED)
            return

        # We need to set the expected internal URL, because the spawner
        # start needs to know it, even though it's not accessible yet.
        # This should be the URL pointing to the lab service we're creating.
        # The service name (at least until we support multiple simultaneous
        # labs) is just "lab".
        self.user_map.set_internal_url(
            username, f"http://lab.{namespace}:8888"
        )

        # Create a task to monitor and inject pod events during spawn.
        evt_task = create_task(
            self.inject_pod_events(
                namespace=namespace,
                username=user.username,
                start_progress=35,
                end_progress=75,
            )
        )
        self._tasks.add(evt_task)
        evt_task.add_done_callback(self._tasks.discard)

        # Now, wait for the pod to spawn.
        await self.await_pod_spawn(namespace=namespace, username=user.username)

    async def create_user_lab_objects(
        self,
        *,
        user: UserInfo,
        lab: LabSpecification,
        image: RSPImage,
        token: str,
    ) -> None:
        username = user.username

        # Doing this in parallel causes a crash, and it's very hard to
        # debug with aiojobs because we do not have the actual failures
        # from the control plane.

        # Doing it sequentially doesn't actually wait for resource creation,
        # because it's an async K8s call, and each call completes quickly.

        await self.create_secrets(
            username=username,
            namespace=self.namespace_from_user(user),
            token=token,
        )
        await self.create_nss(user=user)
        await self.create_file_configmap(user=user)
        await self.create_env(user=user, lab=lab, image=image, token=token)
        await self.create_network_policy(user=user)
        await self.create_quota(user)
        await self.create_lab_service(user=user)

    async def create_secrets(
        self, username: str, token: str, namespace: str
    ) -> None:
        await self.k8s_client.create_secrets(
            secret_list=self.lab_config.secrets,
            username=username,
            token=token,
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

    async def create_nss(self, user: UserInfo) -> None:
        namespace = self.namespace_from_user(user)
        data = self.build_nss(user=user)
        await self.k8s_client.create_configmap(
            name=f"nb-{user.username}-nss",
            namespace=namespace,
            data=data,
        )

    def build_nss(self, user: UserInfo) -> dict[str, str]:
        username = user.username
        pwfile = deepcopy(self.lab_config.files["/etc/passwd"])
        gpfile = deepcopy(self.lab_config.files["/etc/group"])

        pwfile.contents += (
            f"{username}:x:{user.uid}:{user.gid}:"
            f"{user.name}:/home/{username}:/bin/bash"
            "\n"
        )
        groups = user.groups
        for grp in groups:
            gpfile.contents += f"{grp.name}:x:{grp.id}:"
            if grp.id != user.gid:
                gpfile.contents += user.username
            gpfile.contents += "\n"
        data = {
            "/etc/passwd": pwfile.contents,
            "/etc/group": gpfile.contents,
        }
        return data

    async def create_file_configmap(self, user: UserInfo) -> None:
        namespace = self.namespace_from_user(user)
        data = self.build_file_configmap()
        await self.k8s_client.create_configmap(
            name=f"nb-{user.username}-configmap",
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
        *,
        user: UserInfo,
        lab: LabSpecification,
        image: RSPImage,
        token: str,
    ) -> None:
        data = self.build_env(user=user, lab=lab, image=image, token=token)
        await self.k8s_client.create_configmap(
            name=f"nb-{user.username}-env",
            namespace=self.namespace_from_user(user),
            data=data,
        )

    def build_env(
        self,
        *,
        user: UserInfo,
        lab: LabSpecification,
        image: RSPImage,
        token: str,
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
        env.update(
            {
                # We would like to deprecate this, following KubeSpawner, but
                # it's currently used by the lab extensions and by mobu.
                "JUPYTER_IMAGE": image.reference_with_digest,
                # Image data for display frame
                "JUPYTER_IMAGE_SPEC": image.reference_with_digest,
                "IMAGE_DESCRIPTION": image.display_name,
                "IMAGE_DIGEST": image.digest,
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

    async def create_network_policy(self, user: UserInfo) -> None:
        # No corresponding "build" because the policy is hardcoded in the
        # storage driver.
        await self.k8s_client.create_network_policy(
            name=f"nb-{user.username}-env",
            namespace=self.namespace_from_user(user),
        )

    async def create_lab_service(self, user: UserInfo) -> None:
        # No corresponding build because the service is hardcoded in the
        # storage driver.
        await self.k8s_client.create_lab_service(
            username=user.username, namespace=self.namespace_from_user(user)
        )

    async def create_quota(self, user: UserInfo) -> None:
        if not user.quota or not user.quota.notebook:
            return
        await self.k8s_client.create_quota(
            f"nb-{user.username}",
            self.namespace_from_user(user),
            UserResourceQuantum(
                cpu=user.quota.notebook.cpu,
                memory=int(user.quota.notebook.memory * 1024 * 1024 * 1024),
            ),
        )

    async def create_user_pod(
        self, user: UserInfo, resources: UserResources, image: RSPImage
    ) -> None:
        pod_spec = self.build_pod_spec(user, resources, image)
        await self.k8s_client.create_pod(
            name=f"nb-{user.username}",
            namespace=self.namespace_from_user(user),
            pod_spec=pod_spec,
            labels={"app": "lab"},
        )

    def build_lab_config_volumes(
        self, config: list[LabVolume]
    ) -> list[LabVolumeContainer]:
        #
        # Step one: disks specified in config, whether for the lab itself
        # or one of its init containers.
        #
        vols = []
        for storage in config:
            ro = False
            if storage.mode == FileMode.RO:
                ro = True
            vname = storage.container_path.replace("/", "_")[1:]
            if not storage.server:
                vol = V1Volume(
                    host_path=V1HostPathVolumeSource(path=storage.server_path),
                    name=vname,
                )
            else:
                vol = V1Volume(
                    nfs=V1NFSVolumeSource(
                        path=storage.server_path,
                        read_only=ro,
                        server=storage.server,
                    ),
                    name=vname,
                )
            vm = V1VolumeMount(
                mount_path=storage.container_path,
                read_only=ro,
                name=vname,
            )
            vols.append(LabVolumeContainer(volume=vol, volume_mount=vm))
        return vols

    def build_cm_volumes(self, username: str) -> list[LabVolumeContainer]:
        #
        # Step three: other configmap files
        #
        vols = []
        for cfile in self.lab_config.files:
            dscfile = deslashify(cfile)
            cmname = f"nb-{username}-configmap"
            if cfile == "/etc/passwd" or cfile == "/etc/group":
                cmname = f"nb-{username}-nss"
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
                name=f"nb-{username}-secrets",
                secret=V1SecretVolumeSource(
                    secret_name=f"nb-{username}",
                ),
            ),
            volume_mount=V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/secrets",
                name=f"nb-{username}-secrets",
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
                name=f"nb-{username}-secrets",
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
                name=f"nb-{username}-env",
                config_map=V1ConfigMapVolumeSource(
                    name=f"nb-{username}-env",
                ),
            ),
            volume_mount=V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/environment",
                name=f"nb-{username}-env",
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
                name=f"nb-{username}-runtime",
                downward_api=V1DownwardAPIVolumeSource(items=volfiles),
            ),
            volume_mount=V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/runtime",
                name=f"nb-{username}-runtime",
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
        lab_config_vols = self.build_lab_config_volumes(
            self.lab_config.volumes
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
        self, user: UserInfo, resources: UserResources
    ) -> list[V1Container]:
        username = user.username
        init_ctrs = []
        ic_volumes = []
        for ic in self.lab_config.init_containers:
            if ic.volumes is not None:
                ic_volumes = self.build_lab_config_volumes(ic.volumes)
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
                            name=f"nb-{username}-env"
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
            self.logger.debug(f"Added init container {ic.name} ({ic.image})")
            init_ctrs.append(ctr)
        return init_ctrs

    def build_pod_spec(
        self, user: UserInfo, resources: UserResources, image: RSPImage
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
                        key="token", name=f"nb-{user.username}", optional=False
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
        ]
        for spec in self.lab_config.secrets:
            if not spec.env:
                continue
            env_var = V1EnvVar(
                name=spec.env,
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        key=spec.secret_key,
                        name=f"nb-{user.username}",
                        optional=False,
                    )
                ),
            )
            env.append(env_var)

        # Specification for the user's container.
        container = V1Container(
            name="notebook",
            args=["/opt/lsst/software/jupyterlab/runlab.sh"],
            env=env,
            env_from=[
                V1EnvFromSource(
                    config_map_ref=V1ConfigMapEnvSource(
                        name=f"nb-{user.username}-env"
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
            working_dir=f"/home/{user.username}",
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
                supplemental_groups=[x.id for x in user.groups],
            ),
            volumes=volumes,
        )
        return pod

    async def delete_lab(self, username: str) -> None:
        user = self.user_map.get(username)
        if user is None:
            raise UnknownUserError(f"Unknown user {username}")
        self.user_map.set_status(username, LabStatus.TERMINATING)
        self.user_map.clear_internal_url(username)
        #
        # Clear user event queue
        #
        self.event_manager.reset_user(username)
        try:
            await self.info_event(
                username, "Deleting user lab and resources", 25
            )
            await self.k8s_client.delete_namespace(
                self.namespace_from_user(user)
            )
            await self.await_ns_deletion(
                namespace=self.namespace_from_user(user),
                username=user.username,
            )
        except Exception as e:
            if isinstance(e, SlackException):
                e.user = username
            self.logger.exception("Error deleting lab environment")
            await self.failure_event(username, str(e), fatal=True)
            user.status = LabStatus.FAILED

    async def reconcile_user_map(self) -> None:
        self.logger.debug("Reconciling user map with observed state.")
        user_map = self.user_map
        observed_state = await self.k8s_client.get_observed_user_state(
            self.manager_namespace
        )
        known_users = user_map.list_users()
        obs_users = list(observed_state.keys())

        # First pass: take everything in the user map and correct its
        # state (or remove it) if needed.
        for user in known_users:
            u_rec = user_map.get(user)
            if u_rec is None:
                continue  # Shouldn't happen
            status = u_rec.status
            # User was not found by observation
            if user not in obs_users:
                self.logger.warning(
                    f"User {user} not found in observed state."
                )
                if status == LabStatus.FAILED:
                    self.logger.warning(f"Retaining failed state for {user}")
                else:
                    self.logger.warning(f"Removing record for user {user}")
                    self.event_manager.reset_user(user)
                    user_map.remove(user)
            # User was observed to exist
            else:
                obs_rec = observed_state[user]
                if obs_rec.status != status:
                    self.logger.warning(
                        f"User map shows status for {user} as {status}, "
                        + f"but observed is {obs_rec.status}"
                    )
                    if status == LabStatus.FAILED:
                        self.logger.error("Not updating failed status")
                    else:
                        self.logger.warning("Updating user map")
                        user_map.set_status(user, status=obs_rec.status)

        # Second pass: take observed state and create any missing user map
        # entries. This is the normal case after a restart of the lab
        # controller.
        for user in obs_users:
            obs_rec = observed_state[user]
            if user not in known_users:
                self.logger.info(
                    f"No entry for observed user '{user}' in user "
                    + "map.  Creating record from observation"
                )
                user_map.set(user, obs_rec)
