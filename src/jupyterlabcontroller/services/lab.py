import base64
from collections import deque
from dataclasses import dataclass
from typing import Dict, List

from aiojobs import Scheduler

from ..models.v1.domain.config import LabSecrets
from ..models.v1.domain.context import ContextContainer, RequestContext
from ..models.v1.external.lab import LabSpecification, UserQuota
from ..storage.k8s import NetworkPolicySpec, NSCreationError, PodSpec, Secret
from ..utils import get_namespace_prefix


@dataclass
class LabManager:
    lab: LabSpecification
    nublado: ContextContainer
    context: RequestContext

    async def check_for_user(self) -> bool:
        """True if there's a lab for the user, otherwise false."""
        return self.context.user.username in self.nublado.user_map

    async def create_lab(self) -> None:
        """Schedules creation of user lab objects/resources."""
        username = self.context.user.username
        if self.check_for_user():
            estr: str = f"lab already exists for {username}"
            self.nublado.logger.error(f"create_lab failed: {estr}")
            raise RuntimeError(estr)
        #
        # Clear user event queue
        #
        self.nublado.user_map[username].events = deque()
        self.nublado.user_map[username].status = "starting"

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
            await self.nublado.k8s_client.create_namespace(ns_name)
        except NSCreationError as e:
            if e.status == 409:
                self.nublado.logger.info(f"Namespace {ns_name} already exists")
                # ... but we know that we don't have a lab for the user,
                # because we got this far.  So there's a stranded namespace,
                # and we should delete it and recreate it.
                #
                # The spec actually calls for us to delete the lab and then the
                # namespace, but let's just remove the namespace, which should
                # also clean up all its contents.
                await self.nublado.k8s_client.delete_namespace(ns_name)
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
                self.nublado.logger.exception(
                    f"Failed to create namespace {ns_name}: {e}"
                )
                raise

    async def create_user_lab_objects(self) -> None:
        # Initially this will create all the resources in parallel.  If it
        # turns out we need to sequence that, we do this more manually with
        # explicit awaits.
        scheduler: Scheduler = Scheduler(
            close_timeout=self.nublado.config.kubernetes.request_timeout
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
        await self.nublado.k8s_client.create_secret(
            name=f"nb-{self.context.user.username}",
            namespace=self.context.namespace,
            data=data,
        )

    async def merge_controller_secrets(self) -> Dict[str, str]:
        """Merge the user token with whatever secrets we're injecting
        from the lab controller environment."""
        secret_list: LabSecrets = self.nublado.config.lab.secrets
        secret_names: List[str] = []
        secret_keys: List[str] = []
        for sec in secret_list:
            secret_names.append(sec.secretRef)
            if sec.secretKey in secret_keys:
                raise RuntimeError("Duplicate secret key {sec.secretKey}")
            secret_keys.append(sec.secretKey)
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
            secret: Secret = await self.nublado.k8s_client.read_secret(
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

    async def create_nss(self) -> None:
        # FIXME
        data: Dict[str, str] = {
            "/etc/passwd": "",
            "/etc/group": "",
        }
        await self.nublado.k8s_client.create_configmap(
            name=f"nb-{self.context.user.username}-nss",
            namespace=self.context.namespace,
            data=data,
        )

    async def create_env(self) -> None:
        # FIXME
        data: Dict[str, str] = {}
        await self.nublado.k8s_client.create_configmap(
            name=f"nb-{self.context.user.username}-env",
            namespace=self.context.namespace,
            data=data,
        )

    async def create_network_policy(self) -> None:
        # FIXME
        policy = NetworkPolicySpec()
        await self.nublado.k8s_client.create_network_policy(
            name=f"nb-{self.context.user.username}-env",
            namespace=self.context.namespace,
            spec=policy,
        )

    async def create_quota(self) -> None:
        # FIXME
        quota = UserQuota()
        await self.nublado.k8s_client.create_quota(
            name=f"nb-{self.context.user.username}",
            namespace=self.context.namespace,
            quota=quota,
        )

    async def create_user_pod(self) -> None:
        # FIXME
        pod = PodSpec()
        await self.nublado.k8s_client.create_pod(
            name=f"nb-{self.context.user.username}",
            namespace=self.context.namespace,
            pod=pod,
        )

    async def delete_lab_environment(
        self,
        username: str,
    ) -> None:
        # We ignore the request context, because the Hub can shut things
        # down without a user request.
        # Clear Events for user:
        self.nublado.user_map[username].events = deque()
        self.nublado.user_map[username].status = "terminating"
        try:
            await self.nublado.k8s_client.delete_namespace(username)
        except Exception as e:
            self.nublado.logger.error(f"Could not delete lab environment: {e}")
            self.nublado.user_map[username].status = "failed"
            raise
        del self.nublado.user_map[username]
