"""Client for talking to Gafaelfawr."""

from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from ..config import Config
from ..exceptions import GafaelfawrError, InvalidUserError
from ..models.v1.lab import UserInfo


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
        jupyterlabcontroller.exceptions.InvalidUserError
            Token was invalid.
        jupyterlabcontroller.exceptions.GafaelfawrError
            Some other error occurred while talking to Gafaelfawr.
        """
        headers = {"Authorization": f"bearer {token}"}
        try:
            r = await self._http_client.get(self._url, headers=headers)
        except Exception as e:
            msg = f"Unable to contact Gafaelfawr: {str(e)}"
            raise GafaelfawrError(msg) from e
        if r.status_code in (401, 403):
            self._logger.warning("User token is invalid")
            raise InvalidUserError("User token is invalid")
        try:
            r.raise_for_status()
            return UserInfo.parse_obj(r.json())
        except Exception as e:
            msg = f"Unable to parse reply from Gafaelfawr: {str(e)}"
            raise GafaelfawrError(msg) from e
