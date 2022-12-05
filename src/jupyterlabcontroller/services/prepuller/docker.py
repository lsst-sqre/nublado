"""This class will manage communication with the Docker repository in order
to fetch tag information and determine which images are available from the
repository.
"""


from ..storage.docker import DockerStorageClient
from .state import PrepullerState


class PrepullerDockerClient:
    def __init__(
        self,
        namespace: str,
        state: PrepullerState,
        docker_client: DockerStorageClient,
    ) -> None:
        self.logger = docker_client.logger
        self.state = state
        self.namespace = namespace
        self.docker_client = docker_client

    async def refresh_if_needed(self) -> None:
        if self.state.needs_docker_refresh:
            await self.refresh_state_from_docker_repo()

    async def refresh_state_from_docker_repo(self) -> None:
        tag_map = await self.docker_client.get_tag_map()
        self.logger.debug(f"tag_map: {tag_map}")
        self.state.set_remote_images(tag_map)
        self.state.update_docker_check_time()
