import re
from pathlib import Path
from typing import Dict, List, Optional

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ..config import LabConfiguration, LabVolume
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..models.domain.lab import LabVolumeContainer
from ..models.domain.usermap import UserMap
from ..models.tag import StandaloneRSPTag
from ..models.v1.lab import (
    LabSize,
    LabSpecification,
    LabStatus,
    UserData,
    UserInfo,
    UserResourceQuantum,
    UserResources,
)
from ..storage.k8s import (
    ConfigMapEnvSource,
    ConfigMapVolumeSource,
    Container,
    DownwardAPIVolumeFile,
    DownwardAPIVolumeSource,
    EmptyDirVolumeSource,
    EnvFromSource,
    HostPathVolumeSource,
    K8sStorageClient,
    KeyToPath,
    NFSVolumeSource,
    ObjectFieldSelector,
    PodSecurityContext,
    PodSpec,
    ResourceFieldSelector,
    SecretVolumeSource,
    SecurityContext,
    Volume,
    VolumeMount,
)
from .size import SizeManager


class LabManager:
    def __init__(
        self,
        username: str,
        namespace: str,
        manager_namespace: str,
        instance_url: str,
        lab: LabSpecification,
        user_map: UserMap,
        logger: BoundLogger,
        lab_config: LabConfiguration,
        k8s_client: K8sStorageClient,
        user: Optional[UserInfo] = None,
        token: str = "",
    ) -> None:
        self.username = username
        self.namespace = namespace
        self.manager_namespace = manager_namespace
        self.instance_url = instance_url
        self.user_map = user_map
        self.lab = lab
        self.logger = logger
        self.lab_config = lab_config
        self.k8s_client = k8s_client
        self.user = user
        if user is not None:
            if user.username != username:
                raise RuntimeError(
                    f"Username from user record {user.username}"
                    f" does not match {username}"
                )
        self.token = token

    @property
    def resources(self) -> UserResources:
        size_manager = SizeManager(self.lab_config.sizes)
        return size_manager.resources[LabSize(self.lab.options.size)]

    async def check_for_user(self) -> bool:
        """True if there's a lab for the user, otherwise false."""
        r = self.user_map.get(self.username)
        return r is not None

    async def create_lab(self) -> None:
        """Schedules creation of user lab objects/resources."""
        if self.user is None:
            raise RuntimeError("User needed for lab creation")
        username = self.username
        if await self.check_for_user():
            estr: str = f"lab already exists for {username}"
            self.logger.error(f"create_lab failed: {estr}")
            raise RuntimeError(estr)
        #
        # Clear user event queue
        #
        self.user_map.set(
            username,
            UserData.new_from_user_resources(
                user=self.user,
                labspec=self.lab,
                resources=self.resources,
            ),
        )

        #
        # This process has three stages: first is the creation or recreation
        # of the user namespace.  Second is all the resources the user Lab
        # pod will need, and the third is the pod itself.
        #

        await self.create_user_namespace()
        await self.create_user_lab_objects()
        await self.create_user_pod()

    async def create_user_namespace(self) -> None:
        await self.k8s_client.create_user_namespace(self.namespace)

    async def create_user_lab_objects(self) -> None:
        # Initially this will create all the resources in parallel.  If it
        # turns out we need to sequence that, we do this more manually with
        # explicit awaits.
        scheduler = Scheduler(close_timeout=KUBERNETES_REQUEST_TIMEOUT)
        await scheduler.spawn(self.create_secrets())
        await scheduler.spawn(self.create_nss())
        await scheduler.spawn(self.create_file_configmap())
        await scheduler.spawn(self.create_env())
        await scheduler.spawn(self.create_network_policy())
        await scheduler.spawn(self.create_quota())
        self.logger.info("Waiting for user resources to be created.")
        await scheduler.close()
        return

    async def create_secrets(self) -> None:
        await self.k8s_client.create_secrets(
            secret_list=self.lab_config.secrets,
            username=self.username,
            token=self.token,
            source_ns=self.manager_namespace,
            target_ns=self.namespace,
        )

    #
    # We are splitting "build": create the in-memory object representing
    # the resource -- and "create": submit it to Kubernetes -- for the next
    # few things, so that we can more easily unit test the object construction
    # logic.
    #

    async def create_nss(self) -> None:
        data = await self.build_nss()
        await self.k8s_client.create_configmap(
            name=f"nb-{self.username}-nss",
            namespace=self.namespace,
            data=data,
        )

    async def build_nss(self) -> Dict[str, str]:
        pwfile = self.lab_config.files["/etc/passwd"]
        gpfile = self.lab_config.files["/etc/group"]
        if self.user is None:
            raise RuntimeError("Can't create NSS without user")

        pwfile.contents += (
            f"{self.username}:x:{self.user.uid}:{self.user.gid}:"
            f"{self.user.name}:/home/{self.username}:/bin/bash"
            "\n"
        )
        groups = self.user.groups
        for grp in groups:
            gpfile.contents += f"{grp.name}:x:{grp.id}:"
            if grp.id != self.user.gid:
                gpfile.contents += self.user.username
            gpfile.contents += "\n"
        data: Dict[str, str] = {
            "/etc/passwd": pwfile.contents,
            "/etc/group": gpfile.contents,
        }
        return data

    async def create_file_configmap(self) -> None:
        data = await self.build_file_configmap()
        await self.k8s_client.create_configmap(
            name=f"nb-{self.username}-configmap",
            namespace=self.namespace,
            data=data,
        )

    async def build_file_configmap(self) -> Dict[str, str]:
        files = self.lab_config.files
        data: Dict[str, str] = dict()
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

    async def create_env(self) -> None:
        data = await self.build_env()
        await self.k8s_client.create_configmap(
            name=f"nb-{self.user}-env",
            namespace=self.namespace,
            data=data,
        )

    async def build_env(self) -> Dict[str, str]:
        if self.user is None:
            raise RuntimeError("Cannot create user env without user")
        data: Dict[str, str] = dict()
        # Get the static ones from the lab config
        data.update(self.lab_config.env)
        # Get the stuff from the options form
        options = self.lab.options
        if options.debug:
            data["DEBUG"] = "TRUE"
        if options.reset_user_env:
            data["RESET_USER_ENV"] = "TRUE"
        # Values used in more than one place
        jhub_oauth_scopes = (
            f'["access:servers!server={self.username}/", '
            f'"access:servers!user={self.username}"]'
        )
        image = options.image
        # Remember how we decided to pull the image with the digest and tag?
        image_re = r".*:(?P<tag>.*)@sha256:(?P<digest>.*)$"
        image_digest = ""
        image_tag = ""
        i_match = re.compile(image_re).match(image)
        if i_match is not None:
            gd = i_match.groupdict()
            image_digest = gd["digest"]
            image_tag = gd["tag"]
        image_descr = StandaloneRSPTag.parse_tag(image_tag).display_name
        data.update(
            {
                # Image data for display frame
                "JUPYTER_IMAGE": image,
                "JUPYTER_IMAGE_SPEC": image,
                "IMAGE_DESCRIPTION": image_descr,
                "IMAGE_DIGEST": image_digest,
                # Get resource limits
                "CPU_LIMIT": str(self.resources.limits.cpu),
                "MEM_GUARANTEE": str(self.resources.requests.memory),
                "MEM_LIMIT": str(self.resources.limits.memory),
                # Get user/group info
                "EXTERNAL_GID": str(self.user.gid),
                "EXTERNAL_GROUPS": ",".join(
                    [f"{x.name}:{x.id}" for x in self.user.groups]
                ),
                "EXTERNAL_UID": str(self.user.uid),
                # Get global instance URL
                "EXTERNAL_URL": self.instance_url,
                "EXTERNAL_INSTANCE_URL": self.instance_url,
                # Set access token
                "ACCESS_TOKEN": self.token,
                # Set up JupyterHub info
                "JUPYTERHUB_ACTIVITY_URL": (
                    f"http://hub.{self.manager_namespace}:8081/nb/hub/"
                    f"api/users/{self.username}/activity"
                ),
                "JUPYTERHUB_CLIENT_ID": f"jupyterhub-user-{self.username}",
                "JUPYTERHUB_OAUTH_ACCESS_SCOPES": jhub_oauth_scopes,
                "JUPYTERHUB_OAUTH_CALLBACK_URL": (
                    f"/nb/user/{self.username}/oauth_callback"
                ),
                "JUPYTERHUB_OAUTH_SCOPES": jhub_oauth_scopes,
                "JUPYTERHUB_SERVICE_PREFIX": f"/nb/user/{self.username}",
                "JUPYTERHUB_SERVICE_URL": (
                    "http://0.0.0.0:8888/nb/user/" f"{self.username}"
                ),
                "JUPYTERHUB_USER": self.username,
            }
        )
        # FIXME more env injection needed:
        # JPY_API_TOKEN -- guess it has to come from the Hub in the
        # options form response?
        return data

    async def create_network_policy(self) -> None:
        # No corresponding "build" because the policy is hardcoded in the
        # storage driver.
        await self.k8s_client.create_network_policy(
            name=f"nb-{self.user}-env",
            namespace=self.namespace,
        )

    async def create_quota(self) -> None:
        quota = await self.build_namespace_quota()
        if quota is not None:
            await self.k8s_client.create_quota(
                name=f"nb-{self.user}",
                namespace=self.namespace,
                quota=quota,
            )

    async def build_namespace_quota(self) -> Optional[UserResourceQuantum]:
        return self.lab.namespace_quota

    async def create_user_pod(self) -> None:
        if self.user is None:
            raise RuntimeError("Cannot create user pod without user")
        pod = await self.build_pod_spec(self.user)
        await self.k8s_client.create_pod(
            name=f"nb-{self.username}",
            namespace=self.namespace,
            pod=pod,
        )

    async def build_lab_config_volumes(
        self, config: List[LabVolume]
    ) -> List[LabVolumeContainer]:
        #
        # Step one: disks specified in config, whether for the lab itself
        # or one of its init containers.
        #
        vols: List[LabVolumeContainer] = []
        for storage in config:
            ro = False
            if storage.mode == "ro":
                ro = True
            vname = storage.container_path.replace("/", "_")[1:]
            if not storage.server:
                vol = Volume(
                    host_path=HostPathVolumeSource(path=storage.server_path),
                    name=vname,
                )
            else:
                vol = Volume(
                    NFSVolumeSource(
                        path=storage.server_path,
                        read_only=ro,
                        server=storage.server,
                    ),
                    name=vname,
                )
            vm = VolumeMount(
                mount_path=storage.container_path,
                read_only=ro,
                name=vname,
            )
            vols.append(LabVolumeContainer(volume=vol, volume_mount=vm))
        return vols

    async def build_nss_volumes(self) -> List[LabVolumeContainer]:
        #
        # Step two: NSS files
        #
        vols: List[LabVolumeContainer] = []
        for item in ("passwd", "group"):
            vols.append(
                LabVolumeContainer(
                    volume=Volume(
                        name=f"nss-{self.username}-{item}",
                        config_map=ConfigMapVolumeSource(
                            name=f"nb-{self.username}-nss",
                            items=KeyToPath(
                                mode=0x0644,
                                key=item,
                                path=item,
                            ),
                        ),
                    ),
                    volume_mount=VolumeMount(
                        mount_path=f"/etc/{item}",
                        name=f"nss-{self.username}-{item}",
                        read_only=True,
                        sub_path=item,
                    ),
                )
            )
        return vols

    async def build_cm_volumes(self) -> List[LabVolumeContainer]:
        #
        # Step three: other configmap files
        #
        vols: List[LabVolumeContainer] = []
        for cfile in self.lab_config.files:
            if cfile == "/etc/passwd" or cfile == "/etc/group":
                continue  # We already handled these
            path = Path(cfile)
            filename = re.sub(r"[_\.]", "-", str(path.name))
            vols.append(
                LabVolumeContainer(
                    volume=Volume(
                        name=f"nss-{self.username}-{filename}",
                        config_map=ConfigMapVolumeSource(
                            name=f"nb-{self.username}-configmap",
                            items=KeyToPath(
                                mode=0x0644,
                                key=filename,
                                path=cfile,
                            ),
                        ),
                    ),
                    volume_mount=VolumeMount(
                        mount_path=cfile,
                        name=f"nss-{self.username}-{filename}",
                        read_only=True,  # Is that necessarily the case?
                        sub_path=filename,
                    ),
                )
            )
        return vols

    async def build_secret_volume(self) -> LabVolumeContainer:
        #
        # Step four: secret
        #
        # We are going to introduce a new location for all of these and patch
        # things into the existing locations with modifications of runlab.sh.
        # All the secrets will show up in the same directory.  That means
        # we will need to symlink or the existing butler secret.
        sec_vol = LabVolumeContainer(
            volume=Volume(
                name=f"nb-{self.username}-secrets",
                secret=SecretVolumeSource(
                    secret_name=f"nb-{self.username}",
                ),
            ),
            volume_mount=VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/secrets",
                name=f"nb-{self.username}-secrets",
                read_only=True,  # Likely, but I'm not certain
            ),
        )
        return sec_vol

    async def build_env_volume(self) -> LabVolumeContainer:
        #
        # Step five: environment
        #
        env_vol = LabVolumeContainer(
            volume=Volume(
                name=f"nb-{self.username}-env",
                config_map=ConfigMapVolumeSource(
                    name=f"nb-{self.username}-env",
                ),
            ),
            volume_mount=VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/environment",
                name=f"nb-{self.username}-env",
                read_only=False,  # We'd like to be able to update this
            ),
        )
        return env_vol

    async def build_tmp_volume(self) -> LabVolumeContainer:
        return LabVolumeContainer(
            volume=Volume(
                empty_dir=EmptyDirVolumeSource(),
                name="tmp",
            ),
            volume_mount=VolumeMount(
                mount_path="/tmp",
                read_only=False,
                name="tmp",
            ),
        )

    async def build_runtime_volume(self) -> LabVolumeContainer:
        #
        # Step six: introspective information about the pod, only known
        # after pod dispatch.
        #

        # Let's just grab all the fields.
        volfields = [
            "metadata.name",
            "metadata.namespace",
            "metadata.uid",
            "spec.serviceAccountName",
            "spec.nodeName",
            "status.hostIP",
            "status.podIP",
            "metadata.labels",
            "metadata.annotations",
        ]
        resfields = [
            "limits.cpu",
            "requests.cpu",
            "limits.memory",
            "requests.memory",
            "limits.ephemeral-storage",
            "requests.ephemeral-storage",
        ]
        volfiles = [
            DownwardAPIVolumeFile(
                field_ref=ObjectFieldSelector(field_path=x),
                path=x.replace(".", "_").lower(),
            )
            for x in volfields
        ]
        volfiles.extend(
            [
                DownwardAPIVolumeFile(
                    resource_field_ref=ResourceFieldSelector(
                        container_name="notebook",
                        resource=x,
                    ),
                    path=x.replace(".", "_").lower(),
                )
                for x in resfields
            ]
        )
        runtime_vol = LabVolumeContainer(
            volume=Volume(
                name=f"nb-{self.username}-runtime",
                downward_api=DownwardAPIVolumeSource(items=volfiles),
            ),
            volume_mount=VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/runtime",
                name=f"nb-{self.username}-runtime",
                read_only=True,
            ),
        )
        return runtime_vol

    async def build_volumes(self) -> List[LabVolumeContainer]:
        """This stitches together the Volume and VolumeMount definitions
        from each of our sources.
        """
        # Begin with the /tmp empty_dir
        vols: List[LabVolumeContainer] = []
        lab_config_vols = await self.build_lab_config_volumes(
            self.lab_config.volumes
        )
        vols.extend(lab_config_vols)
        nss_vols = await self.build_nss_volumes()
        vols.extend(nss_vols)
        cm_vols = await self.build_cm_volumes()
        vols.extend(cm_vols)
        secret_vol = await self.build_secret_volume()
        vols.append(secret_vol)
        env_vol = await self.build_env_volume()
        vols.append(env_vol)
        tmp_vol = await self.build_tmp_volume()
        vols.append(tmp_vol)
        runtime_vol = await self.build_runtime_volume()
        vols.append(runtime_vol)
        return vols

    async def build_init_ctrs(self) -> List[Container]:
        init_ctrs: List[Container] = []
        ic_volumes: List[LabVolumeContainer] = []
        for ic in self.lab_config.initcontainers:
            if ic.volumes is not None:
                ic_volumes = await self.build_lab_config_volumes(ic.volumes)
            ic_vol_mounts = [x.volume_mount for x in ic_volumes]
            ic_sec_ctx = (
                SecurityContext(
                    run_as_non_root=True,
                    run_as_user=1000,
                    allow_privilege_escalation=False,
                ),
            )
            if ic.privileged:
                ic_sec_ctx = SecurityContext(
                    run_as_non_root=False,
                    run_as_user=0,
                    allow_privilege_escalation=True,
                )
            ctr = Container(
                name=ic.name,
                image=ic.image,
                security_context=ic_sec_ctx,
                volume_mounts=ic_vol_mounts,
            )
            self.logger.debug(f"Added init container {ctr}")
            init_ctrs.append(ctr)
        return init_ctrs

    async def build_pod_spec(self, user: UserInfo) -> PodSpec:
        vol_recs = await self.build_volumes()
        volumes = [x.volume for x in vol_recs]
        vol_mounts = [x.volume_mount for x in vol_recs]
        init_ctrs = await self.build_init_ctrs()
        nb_ctr = Container(
            name="notebook",
            args=["/opt/lsst/software/jupyterlab/runlab.sh"],
            env_from=EnvFromSource(
                config_map_ref=ConfigMapEnvSource(
                    name=f"nb-{self.username}-env"
                )
            ),
            image=self.lab.options.image,
            image_pull_policy="Always",
            security_context=SecurityContext(
                run_as_non_root=True,
                run_as_user=user.uid,
            ),
            volume_mounts=vol_mounts,
            working_dir=f"/home/{user.username}",
        )
        supp_grps = [x.id for x in user.groups]
        # FIXME work out tolerations
        pod = PodSpec(
            init_containers=[init_ctrs],
            containers=[nb_ctr],
            restart_policy="OnFailure",
            security_context=PodSecurityContext(
                run_as_non_root=True,
                fs_group=user.gid,
                supplemental_groups=supp_grps,
            ),
            volumes=volumes,
        )
        self.logger.debug("New pod spec: {pod}")
        return pod


class DeleteLabManager:
    """DeleteLabManager is much simpler, both because it only has one job,
    and because it requires an admin token rather than a user token."""

    def __init__(
        self,
        user_map: UserMap,
        k8s_client: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        self.user_map = user_map
        self.k8s_client = k8s_client
        self.logger = logger

    async def delete_lab_environment(self, username: str) -> None:
        user = self.user_map.get(username)
        if user is None:
            raise RuntimeError(f"Cannot find map for user {username}")
        user.status = LabStatus.TERMINATING
        try:
            await self.k8s_client.delete_namespace(username)
        except Exception as e:
            self.logger.error(f"Could not delete lab environment: {e}")
            user.status = LabStatus.FAILED
            raise
        self.user_map.remove(username)
