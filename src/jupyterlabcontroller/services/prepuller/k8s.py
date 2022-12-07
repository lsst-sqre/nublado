"""Answer questions about the state of images present on nodes.
"""


from copy import copy
from typing import List

from structlog.stdlib import BoundLogger

from ...models.domain.prepuller import NodeContainers, NodeTagImage
from ...models.v1.prepuller import Node, PrepullerConfiguration
from ...storage.k8s import Container, ContainerImage, K8sStorageClient, PodSpec
from .state import PrepullerState
from .tag import PrepullerTagClient
from .util import extract_path_from_image_ref


class PrepullerK8sClient:
    def __init__(
        self,
        state: PrepullerState,
        k8s_client: K8sStorageClient,
        tag_client: PrepullerTagClient,
        logger: BoundLogger,
        config: PrepullerConfiguration,
        namespace: str,
    ) -> None:

        self.k8s_client = k8s_client
        self.state = state
        self.tag_client = tag_client
        self.logger = logger
        self.config = config
        self.namespace = namespace

    async def refresh_if_needed(self) -> None:
        if self.state.needs_k8s_refresh:
            await self.refresh_state_from_k8s()

    async def refresh_state_from_k8s(self) -> None:
        self.logger.debug("Listing nodes and their image contents.")
        # Phase 1: interrogate K8s cluster for images on nodes.
        all_images_by_node = await self.k8s_client.get_image_data()
        self.logger.debug(f"All images on nodes: {all_images_by_node}")
        self.logger.debug("Constructing node pool")
        # Phase 2: construct node objects from image data.
        nodes = self._make_nodes_from_image_data(all_images_by_node)
        self.logger.debug(f"Node pool: {nodes}")
        # Phase 3: get the state of images on those nodes.
        images = self._construct_current_image_state(all_images_by_node)
        self.logger.debug(f"Images by node: {images}")
        # Phase 4: update persistent state.
        self.state.set_images(images)
        self.state.set_nodes(nodes)
        self.state.update_k8s_check_time()

    def _make_nodes_from_image_data(
        self,
        imgdata: NodeContainers,
    ) -> List[Node]:
        return [Node(name=n) for n in imgdata.keys()]

    def _construct_current_image_state(
        self,
        all_images_by_node: NodeContainers,
    ) -> List[NodeTagImage]:
        """Return annotated images representing the state of valid images
        across nodes (including those not enabled).
        """

        # Phase 3A
        # Filter images by config
        filtered_images = self._filter_images_by_config(all_images_by_node)
        # In turn calls _extract_path_from_container()

        self.logger.debug(f"Filtered images: {filtered_images}")

        # Phase 3B
        # get deduplicated NodeTagImages from the Tag client for our
        # filtered images

        node_images = self.tag_client.get_current_image_state(
            images_by_node=filtered_images
        )
        return node_images

    # Phase 3A
    def _filter_images_by_config(
        self,
        images: NodeContainers,
    ) -> NodeContainers:
        r: NodeContainers = dict()

        # FIXME probably should match entire registry/repository, not
        # just last component (in practice, unlikely to matter)
        name = self.config.repository.split("/")[-1]
        self.logger.debug(f"Desired image name: {name}")
        for node in images:
            for c in images[node]:
                path = self._extract_path_from_container(c)
                img_name = path.split("/")[-1]
                if img_name == name:
                    self.logger.debug(f"Adding matching image: {img_name}")
                    if node not in r:
                        r[node] = list()
                    t = copy(c)
                    r[node].append(t)
        return r

    def _extract_path_from_container(self, c: ContainerImage) -> str:
        return extract_path_from_image_ref(c.names[0])

    async def run_prepull_image(self, image: str, nodes: List[str]) -> None:
        pass

    async def create_prepuller_pod_spec(
        self,
        image: str,
        node: str,
    ) -> PodSpec:
        shortname = image.split("/")[-1]

        #        user = UserInfo(
        #            username="prepuller",
        #            name="Prepuller User",
        #            uid=1000,
        #            gid=1000,
        #            groups=[
        #                UserGroup(
        #                    name="prepuller",
        #                    id=1000,
        #                )
        #            ],
        #        )
        return PodSpec(
            containers=[
                Container(
                    name=f"prepull-{shortname}",
                    command=["/bin/sleep", "5"],
                    image=image,
                    working_dir="/tmp",
                )
            ],
            node_name=node,
        )

    async def create_prepuller_pod(
        self, image: str, node: str, name: str, namespace: str
    ) -> None:
        await self.k8s_client.create_pod(
            name=name,
            namespace=namespace,
            pod=self.create_prepuller_pod_spec(image=image, node=node),
        )
