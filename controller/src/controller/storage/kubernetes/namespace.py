"""Storage layer for ``Namespace`` objects."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException, V1Namespace
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger

from ...constants import KUBERNETES_DELETE_TIMEOUT
from ...exceptions import KubernetesError
from ...models.domain.kubernetes import WatchEventType
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
        self, body: V1Namespace, *, replace: bool = False
    ) -> None:
        """Create a new namespace.

        Parameters
        ----------
        body
            Namespace object to create.
        replace
            If `True` and a namespace of that name already exists, delete the
            existing namespace and then try again.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        self._logger.debug("Creating Namespace", name=body.metadata.name)
        try:
            await self._create(body)
        except KubernetesError as e:
            if replace and e.status == 409:
                msg = "Namespace already exists, deleting and recreating"
                self._logger.warning(msg, name=body.metadata.name)
                await self.delete(body.metadata.name, wait=True)
                await self._create(body)
            else:
                raise

    async def delete(self, name: str, *, wait: bool = False) -> None:
        """Delete a namespace.

        If the namespace does not exist, this is silently treated as success.

        Parameters
        ----------
        name
            Name of the namespace.
        wait
            Whether to wait for the namespace to be deleted.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        self._logger.debug("Deleting Namespace", name=name)
        start = current_datetime(microseconds=True)
        timeout = KUBERNETES_DELETE_TIMEOUT
        timeout_error = (
            f"Timed out after {timeout.total_seconds()}s waiting for"
            f"Namespace {name} to be deleted"
        )

        try:
            async with asyncio.timeout(timeout.total_seconds()):
                await self._api.delete_namespace(name)
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting namespace", e, kind="Namespace", name=name
            ) from e
        except TimeoutError as e:
            raise TimeoutError(timeout_error) from e

        if wait:
            elapsed = current_datetime(microseconds=True) - start
            if elapsed > timeout:
                raise TimeoutError(timeout_error)
            try:
                await self.wait_for_deletion(name, timeout - elapsed)
            except TimeoutError as e:
                raise TimeoutError(timeout_error) from e

    async def list(self) -> list[V1Namespace]:
        """List all namespaces.

        Returns
        -------
        list of kubernetes_asyncio.client.V1Namespace
            List of namespaces.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        try:
            objs = await self._api.list_namespace()
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing namespaces", e, kind="Namespace"
            ) from e
        return objs.items

    async def read(self, name: str) -> V1Namespace | None:
        """Read a namespace.

        Parameters
        ----------
        name
            Name of the namespace.

        Returns
        -------
        kubernetes_asyncio.client.V1Namespace or None
            Namespace, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        try:
            return await self._api.read_namespace(name)
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading namespace", e, kind="Namespace", name=name
            ) from e

    async def wait_for_deletion(self, name: str, timeout: timedelta) -> None:
        """Wait for a namespace deletion to complete.

        Parameters
        ----------
        name
            Name of the namespace.
        timeout
            How long to wait for deletion.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        namespace = await self.read(name)
        if not namespace:
            return

        # Wait for the namespace to be deleted.
        watcher = KubernetesWatcher(
            method=self._api.list_namespace,
            object_type=V1Namespace,
            kind="Namespace",
            name=name,
            resource_version=namespace.metadata.resource_version,
            timeout=timeout,
            logger=self._logger,
        )
        try:
            async for event in watcher.watch():
                if event.action == WatchEventType.DELETED:
                    return
        except TimeoutError:
            # If the watch had to be restarted because the resource version
            # was too old and the object was deleted while the watch was
            # restarting, we could have missed the delete event. Therefore,
            # before timing out, do a final check to see if the object is
            # gone.
            if not await self.read(name):
                return
            raise
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for namespace deletion unexpectedly stopped")

    async def _create(self, body: V1Namespace) -> None:
        """Create a namespace (without recreation on conflict).

        Parameters
        ----------
        body
            Namespace object to create.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        try:
            await self._api.create_namespace(body)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating namespace",
                e,
                kind="Namespace",
                name=body.metadata.name,
            ) from e
