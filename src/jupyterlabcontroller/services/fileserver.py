"""Service to manage user fileservers."""


from __future__ import annotations

from typing import Optional

# from ..models.domain.lab import LabVolumeContainer
# as FileserverVolumeContainer
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import LabConfig
from ..models.domain.fileserver import FileserverUserMap
from ..storage.k8s import K8sStorageClient


class FileserverManager:
    def init(
        self,
        *,
        fs_namespace: str,
        user_map: FileserverUserMap,
        logger: BoundLogger,
        lab_config: LabConfig,
        k8s_client: K8sStorageClient,
        slack_client: Optional[SlackWebhookClient] = None,
    ) -> None:
        self.fs_namespace = fs_namespace
        self._logger = logger
        self.lab_config = lab_config
        self.k8s_client = k8s_client
        self._slack_client = slack_client
