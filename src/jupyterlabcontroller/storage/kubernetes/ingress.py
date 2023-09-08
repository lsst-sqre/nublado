"""Storage layer for ``Ingress`` objects."""

from __future__ import annotations

from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, V1Ingress
from structlog.stdlib import BoundLogger

from ...models.domain.kubernetes import WatchEventType
from .deleter import KubernetesObjectDeleter
from .watcher import KubernetesWatcher

__all__ = ["IngressStorage"]


class IngressStorage(KubernetesObjectDeleter):
    """Storage layer for ``Ingress`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        api = client.NetworkingV1Api(api_client)
        super().__init__(
            create_method=api.create_namespaced_ingress,
            delete_method=api.delete_namespaced_ingress,
            list_method=api.list_namespaced_ingress,
            read_method=api.read_namespaced_ingress,
            object_type=V1Ingress,
            kind="Ingress",
            logger=logger,
        )

    def has_ip_address(self, ingress: V1Ingress) -> bool:
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

    async def wait_for_ip_address(
        self, name: str, namespace: str, timeout: timedelta
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
        ingress = await self.read(name, namespace)
        resource_version = None
        if ingress:
            if self.has_ip_address(ingress):
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
            logger=self._logger,
        )
        try:
            async for event in watcher.watch():
                if event.action != WatchEventType.DELETED:
                    if self.has_ip_address(event.object):
                        return
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for ingress IP unexpectedly stopped")
