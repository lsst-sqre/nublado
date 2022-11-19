from typing import Optional

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..constants import DOCKER_SECRETS_PATH
from ..models.domain.docker import DockerCredentialsMap
from .config import configuration_dependency


class DockerCredentialsDependency:
    def __init__(self, filename: str = DOCKER_SECRETS_PATH):
        self._filename = filename
        self._credentials_map: Optional[DockerCredentialsMap] = None

    async def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
        config: Configuration = Depends(configuration_dependency),
    ) -> DockerCredentialsMap:
        self.logger = logger
        return self.map

    @property
    def map(self) -> DockerCredentialsMap:
        if self._credentials_map is None:
            self._credentials_map = DockerCredentialsMap(
                filename=self._filename, logger=self.logger
            )
        return self._credentials_map

    def set_filename(self, filename: str) -> None:
        self._filename = filename
        if self._credentials_map is not None:
            self._credentials_map.load_file(filename)


docker_credentials_dependency = DockerCredentialsDependency()
