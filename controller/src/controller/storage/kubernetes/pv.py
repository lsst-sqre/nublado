"""Storage layer for ``PersistentVolume`` objects."""

from __future__ import annotations

from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import (
    ApiClient,
    ApiException,
    V1PersistentVolume,
)
from structlog.stdlib import BoundLogger

from ...exceptions import ControllerTimeoutError, KubernetesError
from ...models.domain.kubernetes import WatchEventType
from ...timeout import Timeout
from .watcher import KubernetesWatcher

__all__ = ["PersistentVolumeStorage"]


class PersistentVolumeStorage:
    """Storage layer for ``PersistentVolume`` objects.

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
        self,
        body: V1PersistentVolume,
        timeout: Timeout,
        *,
        replace: bool = False,
    ) -> None:
        """Create a new persistent volume.

        Parameters
        ----------
        body
            Persistent Volume object to create.
        timeout
            Timeout on operation.
        replace
            If `True` and a PersistentVolume of that name already exists,
            delete the existing PersistentVolume and then try again.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired waiting for deletion.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        self._logger.debug(
            "Creating Persistent Volume", name=body.metadata.name
        )
        try:
            await self._create(body, timeout)
        except KubernetesError as e:
            if replace and e.status == 409:
                msg = (
                    "Persistent Volume already exists, deleting and recreating"
                )
                self._logger.warning(msg, name=body.metadata.name)
                await self.delete(body.metadata.name, timeout, wait=True)
                await self._create(body, timeout)
            else:
                raise

    async def delete(
        self, name: str, timeout: Timeout, *, wait: bool = False
    ) -> None:
        """Delete a Persistent Volume.

        Parameters
        ----------
        name
            Name of the Persistent Volume.
        timeout
            Timeout on operation.
        wait
            Whether to wait for the persistent volume to be deleted.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        self._logger.debug("Deleting Persistent Volume", name=name)
        try:
            async with timeout.enforce():
                await self._api.delete_persistent_volume(
                    name, _request_timeout=timeout.left()
                )
            if wait:
                await self.wait_for_deletion(name, timeout)
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting persistent volume",
                e,
                kind="PersistentVolume",
                name=name,
            ) from e

    async def list(self, timeout: Timeout) -> list[V1PersistentVolume]:
        """List all persistent volumes.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Returns
        -------
        list of kubernetes_asyncio.client.models.V1PersistentVolume
            List of persistent volumes.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            async with timeout.enforce():
                objs = await self._api.list_persistent_volumes(
                    _request_timeout=timeout.left()
                )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing persistent volumes", e, kind="PersistentVolume"
            ) from e
        return objs.items

    async def read(
        self, name: str, timeout: Timeout
    ) -> V1PersistentVolume | None:
        """Read a persistent volume.

        Parameters
        ----------
        name
            Name of the persistent volume.
        timeout
            Timeout on operation.

        Returns
        -------
        kubernetes_asyncio.client.models.V1PersistentVolume or None
            PersistentVolume, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            async with timeout.enforce():
                return await self._api.read_persistent_volume(
                    name, _request_timeout=timeout.left()
                )
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading persistent volume",
                e,
                kind="PersistentVolume",
                name=name,
            ) from e

    async def wait_for_deletion(self, name: str, timeout: Timeout) -> None:
        """Wait for a persistent volume deletion to complete.

        Parameters
        ----------
        name
            Name of the persistent volume.
        timeout
            How long to wait for deletion.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        pv = await self.read(name, timeout)
        if not pv:
            return

        # Wait for the persistent volume to be deleted.
        watch_timeout = timeout.partial(timedelta(seconds=timeout.left() - 2))
        watcher = KubernetesWatcher(
            method=self._api.list_persistent_volume,
            object_type=V1PersistentVolume,
            kind="PersistentVolume",
            name=name,
            resource_version=pv.metadata.resource_version,
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
        raise RuntimeError(
            "Wait for persistent volume deletion unexpectedly stopped"
        )

    async def _create(
        self, body: V1PersistentVolume, timeout: Timeout
    ) -> None:
        """Create a persistent (without recreation on conflict).

        Parameters
        ----------
        body
            Persistent Volume object to create.
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
            async with timeout.enforce():
                await self._api.create_persistent_volume(
                    body, _request_timeout=timeout.left()
                )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating persistent volume",
                e,
                kind="PersistentVolume",
                name=body.metadata.name,
            ) from e
