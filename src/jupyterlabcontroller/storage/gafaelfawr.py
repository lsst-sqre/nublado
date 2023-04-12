"""Client for talking to Gafaelfawr."""

from __future__ import annotations

from httpx import AsyncClient, HTTPError
from pydantic import ValidationError
from structlog.stdlib import BoundLogger

from ..config import Config
from ..exceptions import (
    GafaelfawrParseError,
    GafaelfawrWebError,
    InvalidTokenError,
)
from ..models.v1.lab import UserInfo

__all__ = ["GafaelfawrStorageClient"]


class GafaelfawrStorageClient:
    """Get user information from Gafaelfawr.

    Parameters
    ----------
    config
        Lab controller configuration.
    http_client
        Shared HTTP client.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        config: Config,
        http_client: AsyncClient,
        logger: BoundLogger,
    ) -> None:
        self._http_client = http_client
        self._logger = logger
        self._url = f"{config.base_url}/auth/api/v1/user-info"

    async def get_user_info(self, token: str) -> UserInfo:
        """Get user information for the user identified by a token.

        Parameters
        ----------
        token
            Gafaelfawr token for user.

        Returns
        -------
        UserInfo
            User metadata.

        Raises
        ------
        GafaelfawrError
            Raised if some error occurred talking to Gafaelfawr or if the
            response from Gafaelfawr could not be parsed.
        InvalidTokenError
            Raised if the token was rejected by Gafaelfawr.
        """
        headers = {"Authorization": f"bearer {token}"}
        try:
            r = await self._http_client.get(self._url, headers=headers)
        except HTTPError as e:
            raise GafaelfawrWebError.from_exception(e) from e
        if r.status_code in (401, 403):
            self._logger.warning("User token is invalid")
            raise InvalidTokenError("User token is invalid")
        try:
            r.raise_for_status()
            return UserInfo.parse_obj(r.json())
        except HTTPError as e:
            raise GafaelfawrWebError.from_exception(e) from e
        except ValidationError as e:
            raise GafaelfawrParseError.from_exception(e) from e
