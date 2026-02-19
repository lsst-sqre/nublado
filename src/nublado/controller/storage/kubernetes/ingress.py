"""Storage layer for ``Ingress`` objects."""

from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, V1Ingress
from structlog.stdlib import BoundLogger

from ...models.domain.kubernetes import WatchEventType
from ...timeout import Timeout
from .deleter import KubernetesObjectDeleter
from .watcher import KubernetesWatcher

__all__ = [
    "IngressStorage",
    "ingress_has_ip_address",
]


def ingress_has_ip_address(ingress: V1Ingress) -> bool:
    """Check whether an ingress has an IP address assigned.

    Parameters
    ----------
    ingress
        Ingress to check.

    Returns
    -------
    bool
        `True` if an IP address is assigned, `False` otherwise.
    """
    if not ingress.status:
        return False
    if not ingress.status.load_balancer:
        return False
    if not ingress.status.load_balancer.ingress:
        return False
    return bool(ingress.status.load_balancer.ingress[0].ip)


class IngressStorage(KubernetesObjectDeleter[V1Ingress]):
    """Storage layer for ``Ingress`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    reconnect_timeout
        How long to wait before explictly restarting Kubernetes watches. This
        can prevent the connection from getting unexpectedly getting closed,
        resulting in 400 errors, or worse, events silently stopping.
    logger
        Logger to use.
    """

    def __init__(
        self,
        api_client: ApiClient,
        reconnect_timeout: timedelta,
        logger: BoundLogger,
    ) -> None:
        api = client.NetworkingV1Api(api_client)
        super().__init__(
            create_method=api.create_namespaced_ingress,
            delete_method=api.delete_namespaced_ingress,
            list_method=api.list_namespaced_ingress,
            read_method=api.read_namespaced_ingress,
            object_type=V1Ingress,
            kind="Ingress",
            reconnect_timeout=reconnect_timeout,
            logger=logger,
        )

    async def wait_for_ip_address(
        self, name: str, namespace: str, timeout: Timeout
    ) -> None:
        """Wait for an ingress to get an IP address assigned.

        The ``Ingress`` object is allowed to not exist when the watch starts,
        since it may be created from a ``GafaelfawrIngress`` custom object.

        Parameters
        ----------
        name
            Name of the ingress.
        namespace
            Namespace of the ingress.
        timeout
            How long to wait for the IP address to be assigned.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the object is not deleted within the delete timeout.
        """
        ingress = await self.read(name, namespace, timeout)
        resource_version = None
        if ingress:
            if ingress_has_ip_address(ingress):
                return
            resource_version = ingress.metadata.resource_version

        # Watch ingress events and wait for it to get an IP address.
        watcher = KubernetesWatcher(
            method=self._list,
            object_type=self._type,
            kind=self._kind,
            name=name,
            namespace=namespace,
            resource_version=resource_version,
            timeout=timeout,
            reconnect_timeout=self._reconnect_timeout,
            logger=self._logger,
        )
        try:
            async with timeout.enforce():
                async for event in watcher.watch():
                    if event.action != WatchEventType.DELETED:
                        if ingress_has_ip_address(event.object):
                            return
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for ingress IP unexpectedly stopped")
