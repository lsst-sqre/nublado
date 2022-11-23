import re
from typing import Dict, Optional

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ..config import LabConfiguration, LabFile
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..models.domain.usermap import UserMap
from ..models.tag import StandaloneRSPTag
from ..models.v1.lab import (
    LabSize,
    LabSpecification,
    LabStatus,
    UserData,
    UserInfo,
    UserResources,
)
from ..storage.k8s import (
    Container,
    K8sStorageClient,
    NetworkPolicySpec,
    PodSecurityContext,
    PodSpec,
)
from .prepuller import PrepullerManager
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
        prepuller_manager: PrepullerManager,
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
        self.prepuller_manager = prepuller_manager
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

    async def _get_file(self, name: str) -> LabFile:
        # This feels like the config data structure should be a dict
        # in the first place.
        files = self.lab_config.files
        for file in files:
            if file.name == name:
                return file
        return LabFile()

    async def create_nss(self) -> None:
        pwfile = await self._get_file("passwd")
        gpfile = await self._get_file("group")
        if self.user is None:
            raise RuntimeError("Can't create NSS without user")

        pwfile.contents += (
            "\n"
            f"{self.username}:x:{self.user.uid}:{self.user.gid}:"
            f"{self.user.name}:/home/{self.username}:/bin/bash"
        )
        groups = self.user.groups
        for grp in groups:
            gpfile.contents += "\n" f"{grp.name}:x:{grp.id}:"
            if grp.id != self.user.gid:
                gpfile.contents += self.user.username
        data: Dict[str, str] = {
            pwfile.mount_path: pwfile.contents,
            gpfile.mount_path: gpfile.contents,
        }
        await self.k8s_client.create_configmap(
            name=f"nb-{self.username}-nss",
            namespace=self.namespace,
            data=data,
        )

    async def create_env(self) -> None:
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
            image_digest = gd["image"]
            image_tag = gd["tag"]
        image_descr = StandaloneRSPTag.from_tag(image_tag).display_name
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
        await self.k8s_client.create_configmap(
            name=f"nb-{self.user}-env",
            namespace=self.namespace,
            data=data,
        )

    async def create_network_policy(self) -> None:
        # FIXME
        policy = NetworkPolicySpec()
        await self.k8s_client.create_network_policy(
            name=f"nb-{self.user}-env",
            namespace=self.namespace,
            spec=policy,
        )

    async def create_quota(self) -> None:
        if self.lab.namespace_quota is not None:
            await self.k8s_client.create_quota(
                name=f"nb-{self.user}",
                namespace=self.namespace,
                quota=self.lab.namespace_quota,
            )

    async def create_user_pod(self) -> None:
        if self.user is None:
            raise RuntimeError("Cannot create user pod without user")
        pod = await self.create_pod_spec(self.user)
        await self.k8s_client.create_pod(
            name=f"nb-{self.username}",
            namespace=self.namespace,
            pod=pod,
        )

    async def create_pod_spec(self, user: UserInfo) -> PodSpec:
        # FIXME: needs a bunch more stuff
        pod = PodSpec(
            containers=[
                Container(
                    name="notebook",
                    args=["/opt/lsst/software/jupyterlab/runlab.sh"],
                    image=self.lab.options.image,
                    security_context=PodSecurityContext(
                        run_as_non_root=True,
                        run_as_user=user.uid,
                    ),
                    working_dir=f"/home/{user.username}",
                )
            ],
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
