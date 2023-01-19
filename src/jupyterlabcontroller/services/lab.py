import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

from kubernetes_asyncio.client.models import (
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
    V1NFSVolumeSource,
    V1ObjectFieldSelector,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceFieldSelector,
    V1SecretVolumeSource,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)
from structlog.stdlib import BoundLogger

from ..config import LabConfiguration, LabVolume
from ..exceptions import LabExistsError, NoUserMapError
from ..models.domain.lab import LabVolumeContainer
from ..models.domain.usermap import UserMap
from ..models.tag import StandaloneRSPTag
from ..models.v1.event import Event, EventTypes
from ..models.v1.lab import (
    LabSize,
    LabSpecification,
    LabStatus,
    UserData,
    UserInfo,
    UserResourceQuantum,
    UserResources,
)
from ..storage.gafaelfawr import GafaelfawrStorageClient
from ..storage.k8s import K8sStorageClient
from ..util import deslashify
from .events import EventManager
from .size import SizeManager

#  argh from aiojobs import Scheduler
#  blargh from ..constants import KUBERNETES_REQUEST_TIMEOUT


class LabManager:
    def __init__(
        self,
        manager_namespace: str,
        instance_url: str,
        user_map: UserMap,
        event_manager: EventManager,
        logger: BoundLogger,
        lab_config: LabConfiguration,
        k8s_client: K8sStorageClient,
        gafaelfawr_client: GafaelfawrStorageClient,
    ) -> None:
        self.manager_namespace = manager_namespace
        self.instance_url = instance_url
        self.user_map = user_map
        self.event_manager = event_manager
        self.logger = logger
        self.lab_config = lab_config
        self.k8s_client = k8s_client
        self.gafaelfawr_client = gafaelfawr_client

    def _namespace_from_user(self, user: UserInfo) -> str:
        return f"{self.manager_namespace}-{user.username}"

    def get_resources(self, lab: LabSpecification) -> UserResources:
        size_manager = SizeManager(self.lab_config.sizes)
        return size_manager.resources[LabSize(lab.options.size)]

    def check_for_user(self, username: str) -> bool:
        """True if there's a lab for the user, otherwise false."""
        r = self.user_map.get(username)
        return r is not None

    async def info_event(self, username: str, message: str, pct: int) -> None:
        if pct < 0 or pct > 100:
            raise RuntimeError(
                "% completion must be between 0 and 100 inclusive"
            )
        ev_queue = self.event_manager.get(username)
        umsg = f"{message} for {username}"
        await ev_queue.asend(Event(data=umsg, event=EventTypes.INFO))
        await ev_queue.asend(Event(data=str(pct), event=EventTypes.PROGRESS))
        self.logger.info(f"Event: {umsg}: {pct}% ")

    async def completion_event(self, username: str) -> None:
        ev_queue = self.event_manager.get(username)
        cstr = f"Operation complete for {username}"
        await ev_queue.asend(
            Event(
                data=cstr,
                event=EventTypes.COMPLETE,
            )
        )
        self.logger.info(cstr)

    async def failure_event(
        self, username: str, message: str, fatal: bool = True
    ) -> None:
        ev_queue = self.event_manager.get(username)
        umsg = message + f" for {username}"
        await ev_queue.asend(Event(data=umsg, event=EventTypes.ERROR))
        if fatal:
            await ev_queue.asend(
                Event(
                    data=f"Lab creation failed for {username}",
                    event=EventTypes.FAILED,
                )
            )
        estr = f"Event: {umsg}"
        if fatal:
            estr = "Fatal e" + estr[1:]
        self.logger.error(estr)

    async def create_lab(self, token: str, lab: LabSpecification) -> None:
        """Schedules creation of user lab objects/resources."""
        user = await self.gafaelfawr_client.get_user(token)
        username = user.username
        namespace = self._namespace_from_user(user)

        # unclear if we should clear the event queue before this.  Probably not
        # because we don't want to wipe out the existing log, since we will
        # not be spawning.
        if self.check_for_user(username):
            await self.failure_event(username, "lab already exists")
            raise LabExistsError(f"lab already exists for {username}")
        # Add a new usermap entry
        self.user_map.set(
            username,
            UserData.new_from_user_resources(
                user=user,
                labspec=lab,
                resources=self.get_resources(lab),
            ),
        )
        #
        # Clear user event queue
        #
        self.event_manager.remove(username)
        #
        # This process has three stages: first is the creation or recreation
        # of the user namespace.  V1Second is all the resources the user Lab
        # pod will need, and the third is the pod itself.
        #

        await self.info_event(username, "Lab creation initiated", 2)
        await self.k8s_client.create_user_namespace(namespace)
        await self.info_event(username, "User namespace created", 5)
        await self.create_user_lab_objects(user=user, token=token, lab=lab)
        await self.info_event(username, "Resource objects created", 40)
        await self.create_user_pod(user=user, lab=lab)
        await self.info_event(username, "Pod created", 75)
        self.user_map.set_status(user.username, status=LabStatus.RUNNING)
        await self.completion_event(username)

    async def create_user_lab_objects(
        self,
        user: UserInfo,
        token: str,
        lab: LabSpecification,
    ) -> None:
        username = user.username

        # Doing this in parallel causes a crash, and it's very hard to
        # debug with aiojobs because we do not have the actual failures
        # from the control plane.

        # Doing it sequentially doesn't actually wait for resource creation,
        # because it's an async K8s call, and each call completes quickly.

        try:
            await self.create_secrets(
                username=username,
                namespace=self._namespace_from_user(user),
                token=token,
            )
            await self.info_event(username, "Secrets created", 10)
            await self.create_nss(user=user)
            await self.info_event(username, "NSS files created", 15)
            await self.create_file_configmap(user=user)
            await self.info_event(username, "Config files created", 20)
            await self.create_env(user=user, lab=lab, token=token)
            await self.info_event(username, "Environment created", 25)
            await self.create_network_policy(user=user)
            await self.info_event(username, "Network policy created", 25)
            await self.create_quota(user=user, lab=lab)
            await self.info_event(username, "Quota created", 30)
            await self.create_lab_service(user=user)
            await self.info_event(username, "Service created", 35)
        except Exception as exc:
            await self.failure_event(username, f"Exception: '{exc}'")
        return

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

    #
    # We are splitting "build": create the in-memory object representing
    # the resource -- and "create": submit it to Kubernetes -- for the next
    # few things, so that we can more easily unit test the object construction
    # logic.
    #

    async def create_nss(self, user: UserInfo) -> None:
        namespace = self._namespace_from_user(user)
        data = self.build_nss(user=user)
        await self.k8s_client.create_configmap(
            name=f"nb-{user.username}-nss",
            namespace=namespace,
            data=data,
        )

    def build_nss(self, user: UserInfo) -> Dict[str, str]:
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
        data: Dict[str, str] = {
            "/etc/passwd": pwfile.contents,
            "/etc/group": gpfile.contents,
        }
        return data

    async def create_file_configmap(self, user: UserInfo) -> None:
        namespace = self._namespace_from_user(user)
        data = self.build_file_configmap()
        await self.k8s_client.create_configmap(
            name=f"nb-{user.username}-configmap",
            namespace=namespace,
            data=data,
        )

    def build_file_configmap(self) -> Dict[str, str]:
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

    async def create_env(
        self, user: UserInfo, lab: LabSpecification, token: str
    ) -> None:
        data = self.build_env(user=user, lab=lab, token=token)
        await self.k8s_client.create_configmap(
            name=f"nb-{user.username}-env",
            namespace=self._namespace_from_user(user),
            data=data,
        )

    def build_env(
        self, user: UserInfo, lab: LabSpecification, token: str
    ) -> Dict[str, str]:
        # Get the static env vars from the lab config
        data = deepcopy(self.lab_config.env)
        # Get the stuff from the options form
        options = lab.options
        if options.debug:
            data["DEBUG"] = "TRUE"
        if options.reset_user_env:
            data["RESET_USER_ENV"] = "TRUE"
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
        resources = self.get_resources(lab=lab)
        #
        # More of these, eventually, will come from the options form.
        #
        data.update(
            {
                # Image data for display frame
                "JUPYTER_IMAGE": image,
                "JUPYTER_IMAGE_SPEC": image,
                "IMAGE_DESCRIPTION": image_descr,
                "IMAGE_DIGEST": image_digest,
                # Get resource limits
                "CPU_LIMIT": str(resources.limits.cpu),
                "MEM_GUARANTEE": str(resources.requests.memory),
                "MEM_LIMIT": str(resources.limits.memory),
                # Get user/group info
                "EXTERNAL_GID": str(user.gid),
                "EXTERNAL_GROUPS": ",".join(
                    [f"{x.name}:{x.id}" for x in user.groups]
                ),
                "EXTERNAL_UID": str(user.uid),
                # Get global instance URL
                "EXTERNAL_URL": self.instance_url,
                "EXTERNAL_INSTANCE_URL": self.instance_url,
                # Set access token
                "ACCESS_TOKEN": token,
            }
        )
        # Now inject from options form (overwrites existing values).
        # All JupyterHub config comes in from here.
        for key in lab.env:
            data.update({key: lab.env[key]})
        return data

    async def create_network_policy(self, user: UserInfo) -> None:
        # No corresponding "build" because the policy is hardcoded in the
        # storage driver.
        await self.k8s_client.create_network_policy(
            name=f"nb-{user.username}-env",
            namespace=self._namespace_from_user(user),
        )

    async def create_lab_service(self, user: UserInfo) -> None:
        # No corresponding build because the service is hardcoded in the
        # storage driver.
        await self.k8s_client.create_lab_service(
            username=user.username, namespace=self._namespace_from_user(user)
        )

    async def create_quota(
        self, user: UserInfo, lab: LabSpecification
    ) -> None:
        quota = self.build_namespace_quota(lab=lab)
        if quota is not None:
            await self.k8s_client.create_quota(
                name=f"nb-{user.username}",
                namespace=self._namespace_from_user(user),
                quota=quota,
            )

    def build_namespace_quota(
        self, lab: LabSpecification
    ) -> Optional[UserResourceQuantum]:
        return lab.namespace_quota

    async def create_user_pod(
        self, user: UserInfo, lab: LabSpecification
    ) -> None:
        pod = self.build_pod_spec(user=user, lab=lab)
        snames = [x.secret_name for x in self.lab_config.secrets]
        needs_pull_secret = False
        if "pull-secret" in snames:
            needs_pull_secret = True
        # FIXME
        # Here we should create a K8s pod watch, and then reflect its
        # events into the user queue, removing it when the pod creation
        # has completed.
        await self.k8s_client.create_pod(
            name=f"nb-{user.username}",
            namespace=self._namespace_from_user(user),
            pod=pod,
            pull_secret=needs_pull_secret,
            labels={"app": "lab"},
        )

    def build_lab_config_volumes(
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

    def build_cm_volumes(self, username: str) -> List[LabVolumeContainer]:
        #
        # Step three: other configmap files
        #
        vols: List[LabVolumeContainer] = []
        for cfile in self.lab_config.files:
            dscfile = deslashify(cfile)
            cmname = f"nb-{username}-configmap"
            if cfile == "/etc/passwd" or cfile == "/etc/group":
                cmname = f"nb-{username}-nss"
            path = Path(cfile)
            bname = str(path.name)
            # dname = str(path.parent)
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
        # We are going to introduce a new location for all of these and patch
        # things into the existing locations with modifications of runlab.sh.
        # All the secrets will show up in the same directory.  That means
        # we will need to symlink or the existing butler secret.
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
                read_only=True,  # Likely, but I'm not certain
            ),
        )
        return sec_vol

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
        # volfiles = [
        #    V1DownwardAPIVolumeFile(
        #        field_ref=V1ObjectFieldSelector(field_path=x),
        #        path=x.replace(".", "_").lower(),
        #    )
        #    for x in volfields
        # ]
        volfiles: List[V1DownwardAPIVolumeFile] = list()
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

    def build_volumes(self, username: str) -> List[LabVolumeContainer]:
        """This stitches together the Volume and VolumeMount definitions
        from each of our sources.
        """
        # Begin with the /tmp empty_dir
        vols: List[LabVolumeContainer] = []
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

    def build_init_ctrs(self) -> List[V1Container]:
        init_ctrs: List[V1Container] = []
        ic_volumes: List[LabVolumeContainer] = []
        for ic in self.lab_config.initcontainers:
            if ic.volumes is not None:
                ic_volumes = self.build_lab_config_volumes(ic.volumes)
            ic_vol_mounts = [x.volume_mount for x in ic_volumes]
            ic_sec_ctx = (
                V1SecurityContext(
                    run_as_non_root=True,
                    run_as_user=1000,
                    allow_privilege_escalation=False,
                ),
            )
            if ic.privileged:
                ic_sec_ctx = V1SecurityContext(
                    run_as_non_root=False,
                    run_as_user=0,
                    allow_privilege_escalation=True,
                )
            ctr = V1Container(
                name=ic.name,
                image=ic.image,
                security_context=ic_sec_ctx,
                volume_mounts=ic_vol_mounts,
            )
            self.logger.debug(f"Added init container {ctr}")
            init_ctrs.append(ctr)
        return init_ctrs

    def build_pod_spec(
        self, user: UserInfo, lab: LabSpecification
    ) -> V1PodSpec:
        username = user.username
        vol_recs = self.build_volumes(username=username)
        volumes = [x.volume for x in vol_recs]
        vol_mounts = [x.volume_mount for x in vol_recs]
        init_ctrs = self.build_init_ctrs()
        env = [
            # Because spec.nodeName is not reflected in
            # DownwardAPIVolumeSource:
            # https://github.com/kubernetes/kubernetes/issues/64168
            V1EnvVar(
                name="K8S_NODE_NAME",
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="spec.nodeName")
                ),
            ),
        ]
        nb_ctr = V1Container(
            name="notebook",
            args=["/opt/lsst/software/jupyterlab/runlab.sh"],
            env=env,
            env_from=[
                V1EnvFromSource(
                    config_map_ref=V1ConfigMapEnvSource(
                        name=f"nb-{username}-env"
                    )
                ),
            ],
            image=lab.options.image,
            image_pull_policy="Always",
            ports=[
                V1ContainerPort(
                    container_port=8888,
                    name="jupyterlab",
                ),
            ],
            security_context=V1SecurityContext(
                run_as_non_root=True,
                run_as_user=user.uid,
            ),
            volume_mounts=vol_mounts,
            working_dir=f"/home/{username}",
        )
        supp_grps = [x.id for x in user.groups]
        # FIXME work out tolerations
        pod = V1PodSpec(
            init_containers=init_ctrs,
            containers=[nb_ctr],
            restart_policy="OnFailure",
            security_context=V1PodSecurityContext(
                run_as_non_root=True,
                fs_group=user.gid,
                supplemental_groups=supp_grps,
            ),
            volumes=volumes,
        )
        return pod

    async def delete_lab(self, username: str) -> None:
        user = self.user_map.get(username)
        if user is None:
            raise NoUserMapError(f"Cannot find map for user {username}")
        user.status = LabStatus.TERMINATING
        #
        # Clear user event queue
        #
        self.event_manager.remove(username)
        try:
            await self.info_event(
                username, "Deleting user lab and resources", 25
            )
            await self.k8s_client.delete_namespace(
                self._namespace_from_user(user)
            )
            await self.completion_event(
                username,
            )
        except Exception as e:
            emsg = f"Could not delete lab environment: '{e}'"
            await self.failure_event(username, emsg)
            user.status = LabStatus.FAILED
            raise
        self.user_map.remove(username)
