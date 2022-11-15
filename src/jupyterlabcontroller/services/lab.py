import base64
from collections import deque
from dataclasses import dataclass
from typing import Dict, List

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ..config import LabFile, LabSecret
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..models.context import Context
from ..models.v1.lab import LabSpecification, UserData, UserQuota
from ..storage.k8s import (
    Container,
    NetworkPolicySpec,
    NSCreationError,
    PodSecurityContext,
    PodSpec,
    Secret,
)
from ..utils import get_namespace_prefix, quota_from_size


@dataclass
class LabManager:
    lab: LabSpecification
    context: Context

    @property
    def user(self) -> str:
        if self.context.user is None:
            return ""
        return self.context.user.username

    @property
    def quota(self) -> UserQuota:
        return quota_from_size(
            size=self.lab.options.size, config=self.context.config
        )

    @property
    def logger(self) -> BoundLogger:
        return self.context.logger

    async def check_for_user(self) -> bool:
        """True if there's a lab for the user, otherwise false."""
        r = self.context.user_map.get(self.user)
        return r is not None

    async def create_lab(self) -> None:
        """Schedules creation of user lab objects/resources."""
        if self.context.user is None:
            raise RuntimeError("User needed for lab creation")
        username = self.user
        if await self.check_for_user():
            estr: str = f"lab already exists for {username}"
            self.context.logger.error(f"create_lab failed: {estr}")
            raise RuntimeError(estr)
        #
        # Clear user event queue
        #
        self.context.user_map[username] = UserData.new_from_user_lab_quota(
            user=self.context.user, labspec=self.lab, quota=self.quota
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
        ns_retries: int = 0
        ns_max_retries: int = 5
        ns_name = self.context.namespace
        try:
            await self.context.k8s_client.create_namespace(ns_name)
        except NSCreationError as e:
            if e.status == 409:
                self.context.logger.info(f"Namespace {ns_name} already exists")
                # ... but we know that we don't have a lab for the user,
                # because we got this far.  So there's a stranded namespace,
                # and we should delete it and recreate it.
                #
                # The spec actually calls for us to delete the lab and then the
                # namespace, but let's just remove the namespace, which should
                # also clean up all its contents.
                await self.context.k8s_client.delete_namespace(ns_name)
                ns_retries += 1
                # Give up after a while.
                if ns_retries > ns_max_retries:
                    raise RuntimeError(
                        "Maximum namespace creation retries "
                        f"({ns_max_retries}) exceeded"
                    )
                # Just try again, and return *that* one's return value.
                return await self.create_user_namespace()
            else:
                self.context.logger.exception(
                    f"Failed to create namespace {ns_name}: {e}"
                )
                raise

    async def create_user_lab_objects(self) -> None:
        # Initially this will create all the resources in parallel.  If it
        # turns out we need to sequence that, we do this more manually with
        # explicit awaits.
        scheduler: Scheduler = Scheduler(
            close_timeout=KUBERNETES_REQUEST_TIMEOUT
        )
        await scheduler.spawn(self.create_secrets())
        await scheduler.spawn(self.create_nss())
        await scheduler.spawn(self.create_env())
        await scheduler.spawn(self.create_network_policy())
        await scheduler.spawn(self.create_quota())
        await scheduler.close()
        return

    async def create_secrets(self) -> None:
        data: Dict[str, str] = await self.merge_controller_secrets()
        await self.context.k8s_client.create_secret(
            name=f"nb-{self.user}",
            namespace=self.context.namespace,
            data=data,
        )

    async def merge_controller_secrets(self) -> Dict[str, str]:
        """Merge the user token with whatever secrets we're injecting
        from the lab controller environment."""
        secret_list: List[LabSecret] = self.context.config.lab.secrets
        secret_names: List[str] = []
        secret_keys: List[str] = []
        for sec in secret_list:
            secret_names.append(sec.secret_name)
            if sec.secret_key in secret_keys:
                raise RuntimeError("Duplicate secret key {sec.secret_key}")
            secret_keys.append(sec.secret_key)
        # In theory, we should parallelize the secret reads.  But in practice
        # it makes life a lot more complex, and we will have at most two:
        # the controller secret and a pull secret.
        #
        # There is also some subtlety about the secret type.  For now we are
        # going to assume everything is "Opaque" (and thus can contain
        # arbitrary data).

        base64_data: Dict[str, str] = {}
        namespace: str = get_namespace_prefix()
        for name in secret_names:
            secret: Secret = await self.context.k8s_client.read_secret(
                name=name, namespace=namespace
            )
            # Retrieve matching keys
            for key in secret.data:
                if key in secret_keys:
                    base64_data[key] = secret.data[key]
        # There's no point in decoding it; all we're gonna do is pass it
        # down to create a secret as base64 anyway.
        if "token" in base64_data:
            raise RuntimeError("'token' must come from the user token")
        base64_data["token"] = str(
            base64.b64encode(self.context.token.encode("utf-8"))
        )
        return base64_data

    async def _get_file(self, name: str) -> LabFile:
        # This feels like the config data structure should be a dict
        # in the first place.
        files: List[LabFile] = self.context.config.lab.files
        for file in files:
            if file.name == name:
                return file
        return LabFile()

    async def create_nss(self) -> None:
        pwfile: LabFile = await self._get_file("passwd")
        gpfile: LabFile = await self._get_file("group")
        # FIXME: Now edit those two...
        data: Dict[str, str] = {
            pwfile.mountPath: pwfile.contents,
            gpfile.mountPath: gpfile.contents,
        }
        await self.context.k8s_client.create_configmap(
            name=f"nb-{self.user}-nss",
            namespace=self.context.namespace,
            data=data,
        )

    async def create_env(self) -> None:
        data: Dict[str, str] = {}
        data.update(self.context.config.lab.env)
        # FIXME more env injection needed
        await self.context.k8s_client.create_configmap(
            name=f"nb-{self.user}-env",
            namespace=self.context.namespace,
            data=data,
        )

    async def create_network_policy(self) -> None:
        # FIXME
        policy = NetworkPolicySpec()
        await self.context.k8s_client.create_network_policy(
            name=f"nb-{self.user}-env",
            namespace=self.context.namespace,
            spec=policy,
        )

    async def create_quota(self) -> None:
        await self.context.k8s_client.create_quota(
            name=f"nb-{self.user}",
            namespace=self.context.namespace,
            quota=self.quota,
        )

    async def create_user_pod(self) -> None:
        pod = await self.create_pod_spec()
        await self.context.k8s_client.create_pod(
            name=f"nb-{self.user}",
            namespace=self.context.namespace,
            pod=pod,
        )

    async def create_pod_spec(self) -> PodSpec:
        # FIXME: needs a bunch more stuff
        if self.context.user is None:
            raise RuntimeError("User required to create pod spec")
        pod = PodSpec(
            containers=[
                Container(
                    name="notebook",
                    args=["/opt/lsst/software/jupyterlab/runlab.sh"],
                    image=self.lab.options.image,
                    security_context=PodSecurityContext(
                        run_as_non_root=True,
                        run_as_user=self.context.user.uid,
                    ),
                    working_dir=f"/home/{self.user}",
                )
            ],
        )
        self.logger.debug("New pod spec: {pod}")
        return pod

    async def delete_lab_environment(
        self,
        username: str,
    ) -> None:
        # We ignore the request context, because the Hub can shut things
        # down without a user request.
        # Clear Events for user:
        self.context.user_map[username].events = deque()
        self.context.user_map[username].status = "terminating"
        try:
            await self.context.k8s_client.delete_namespace(username)
        except Exception as e:
            self.context.logger.error(f"Could not delete lab environment: {e}")
            self.context.user_map[username].status = "failed"
            raise
        del self.context.user_map[username]
