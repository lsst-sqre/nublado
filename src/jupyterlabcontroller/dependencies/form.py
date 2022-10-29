from typing import Optional

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..models.v1.external.userdata import UserInfo
from ..storage.form import FormManager
from ..storage.labs import LabClient
from .token import user_dependency


class FormManagerDependency:
    _manager: Optional[FormManager] = None

    async def __call__(
        self,
        user: UserInfo = Depends(user_dependency),
        logger: BoundLogger = Depends(logger_dependency),
    ) -> LabClient:
        if self._manager is None:
            self.manager()
        return self._manager

    def manager(
        self, user: UserInfo, logger: BoundLogger, config: Config
    ) -> None:
        self._manager = FormManager(user=user, logger=logger, config=config)
        return self._manager


form_manager_dependency = FormManagerDependency()
