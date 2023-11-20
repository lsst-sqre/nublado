"""Storage layer for ``Namespace`` objects."""

from __future__ import annotations

from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException, V1Namespace
from structlog.stdlib import BoundLogger

from ...exceptions import ControllerTimeoutError, KubernetesError
from ...models.domain.kubernetes import WatchEventType
from ...timeout import Timeout
from .watcher import KubernetesWatcher

__all__ = ["NamespaceStorage"]


class NamespaceStorage:
    """Storage layer for ``Namespace`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        self._api = client.CoreV1Api(api_client)
        self._logger = logger

    async def create(
        self, body: V1Namespace, timeout: Timeout, *, replace: bool = False
    ) -> None:
        """Create a new namespace.

        Parameters
        ----------
        body
            Namespace object to create.
        timeout
            Timeout on operation.
        replace
            If `True` and a namespace of that name already exists, delete the
            existing namespace and then try again.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired waiting for deletion.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        self._logger.debug("Creating Namespace", name=body.metadata.name)
        try:
            await self._create(body, timeout)
        except KubernetesError as e:
            if replace and e.status == 409:
                msg = "Namespace already exists, deleting and recreating"
                self._logger.warning(msg, name=body.metadata.name)
                await self.delete(body.metadata.name, timeout, wait=True)
                await self._create(body, timeout)
            else:
                raise

    async def delete(
        self, name: str, timeout: Timeout, *, wait: bool = False
    ) -> None:
        """Delete a namespace.

        If the namespace does not exist, this is silently treated as success.

        Parameters
        ----------
        name
            Name of the namespace.
        timeout
            Timeout on operation.
        wait
            Whether to wait for the namespace to be deleted.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        self._logger.debug("Deleting Namespace", name=name)
        try:
            async with timeout.enforce():
                await self._api.delete_namespace(
                    name, _request_timeout=timeout.left()
                )
                if wait:
                    await self.wait_for_deletion(name, timeout)
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting namespace", e, kind="Namespace", name=name
            ) from e

    async def list(self, timeout: Timeout) -> list[V1Namespace]:
        """List all namespaces.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Returns
        -------
        list of kubernetes_asyncio.client.V1Namespace
            List of namespaces.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            objs = await self._api.list_namespace(
                _request_timeout=timeout.left()
            )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing namespaces", e, kind="Namespace"
            ) from e
        return objs.items

    async def read(self, name: str, timeout: Timeout) -> V1Namespace | None:
        """Read a namespace.

        Parameters
        ----------
        name
            Name of the namespace.
        timeout
            Timeout on operation.

        Returns
        -------
        kubernetes_asyncio.client.V1Namespace or None
            Namespace, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            return await self._api.read_namespace(
                name, _request_timeout=timeout.left()
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading namespace", e, kind="Namespace", name=name
            ) from e

    async def wait_for_deletion(self, name: str, timeout: Timeout) -> None:
        """Wait for a namespace deletion to complete.

        Parameters
        ----------
        name
            Name of the namespace.
        timeout
            How long to wait for deletion.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        namespace = await self.read(name, timeout)
        if not namespace:
            return

        # Wait for the namespace to be deleted.
        watch_timeout = timeout.partial(timedelta(seconds=timeout.left() - 2))
        watcher = KubernetesWatcher(
            method=self._api.list_namespace,
            object_type=V1Namespace,
            kind="Namespace",
            name=name,
            resource_version=namespace.metadata.resource_version,
            timeout=watch_timeout,
            logger=self._logger,
        )
        try:
            async with watch_timeout.enforce():
                async for event in watcher.watch():
                    if event.action == WatchEventType.DELETED:
                        return
        except ControllerTimeoutError:
            # If the watch had to be restarted because the resource version
            # was too old and the object was deleted while the watch was
            # restarting, we could have missed the delete event. Therefore,
            # before timing out, do a final check with a short timeout to see
            # if the object is gone.
            read_timeout = timeout.partial(timedelta(seconds=2))
            if not await self.read(name, read_timeout):
                return
            raise
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for namespace deletion unexpectedly stopped")

    async def _create(self, body: V1Namespace, timeout: Timeout) -> None:
        """Create a namespace (without recreation on conflict).

        Parameters
        ----------
        body
            Namespace object to create.
        timeout
            How long to wait for deletion.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            await self._api.create_namespace(
                body, _request_timeout=timeout.left()
            )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating namespace",
                e,
                kind="Namespace",
                name=body.metadata.name,
            ) from e
