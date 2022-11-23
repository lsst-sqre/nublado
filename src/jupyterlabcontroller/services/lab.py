import base64
from typing import Dict, List, Optional

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ..config import LabConfiguration, LabFile, LabSecret
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..models.domain.usermap import UserMap
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
    Secret,
)
from .prepuller import PrepullerManager
from .size import SizeManager


class LabManager:
    def __init__(
        self,
        username: str,
        namespace: str,
        manager_namespace: str,
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
        data = await self.merge_controller_secrets()
        await self.k8s_client.create_secret(
            name=f"nb-{self.username}",
            namespace=self.namespace,
            data=data,
        )
        pull_secrets = await self.copy_pull_secrets()
        if pull_secrets:
            await self.k8s_client.create_secret(
                name="pull-secret",
                namespace=self.namespace,
                data=pull_secrets,
                secret_type="kubernetes.io/dockerconfigjson",
            )

    async def copy_pull_secrets(self) -> Dict[str, str]:
        secret_list: List[LabSecret] = self.lab_config.secrets
        secnames = [x.secret_name for x in secret_list]
        if "pull-secret" not in secnames:
            return dict()
        secret = await self.k8s_client.read_secret(
            name="pull-secret", namespace=self.manager_namespace
        )
        return secret.data

    async def merge_controller_secrets(self) -> Dict[str, str]:
        """Merge the user token with whatever secrets we're injecting
        from the lab controller environment."""
        secret_list: List[LabSecret] = self.lab_config.secrets
        secret_names: List[str] = list()
        secret_keys: List[str] = list()
        for sec in secret_list:
            if sec.secret_name == "pull-secret":
                continue  # Pull-secret is special
            secret_names.append(sec.secret_name)
            if sec.secret_key in secret_keys:
                raise RuntimeError("Duplicate secret key {sec.secret_key}")
            secret_keys.append(sec.secret_key)
        # In theory, we should parallelize the secret reads.  But in practice
        # it makes life a lot more complex, and we probably just have one,
        # the controller secret.  Pull-secret will be handled separately.
        base64_data: Dict[str, str] = dict()
        for name in secret_names:
            secret: Secret = await self.k8s_client.read_secret(
                name=name, namespace=self.manager_namespace
            )
            # Retrieve matching keys
            for key in secret.data:
                if key in secret_keys:
                    base64_data[key] = secret.data[key]
        # There's no point in decoding it; all we're gonna do is pass it
        # down to create a secret as base64 anyway.
        if "token" in base64_data:
            raise RuntimeError("'token' must come from the user token")
        if not self.token:
            raise RuntimeError("User token cannot be empty")
        base64_data["token"] = str(
            base64.b64encode(self.token.encode("utf-8"))
        )
        return base64_data

    async def _get_file(self, name: str) -> LabFile:
        # This feels like the config data structure should be a dict
        # in the first place.
        files: List[LabFile] = self.lab_config.files
        for file in files:
            if file.name == name:
                return file
        return LabFile()

    async def create_nss(self) -> None:
        pwfile: LabFile = await self._get_file("passwd")
        gpfile: LabFile = await self._get_file("group")
        # FIXME: Now edit those two...
        data: Dict[str, str] = {
            pwfile.mount_path: pwfile.contents,
            gpfile.mount_path: gpfile.contents,
        }
        await self.k8s_client.create_configmap(
            name=f"nb-{self.user}-nss",
            namespace=self.namespace,
            data=data,
        )

    async def create_env(self) -> None:
        data: Dict[str, str] = dict()
        data.update(self.lab_config.env)
        # FIXME more env injection needed
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
