"""Answer questions about the state of images present on nodes.
"""


from copy import copy
from typing import List

from kubernetes_asyncio.client.models import V1Container, V1PodSpec
from structlog.stdlib import BoundLogger

from ...models.domain.prepuller import NodeContainers, NodeTagImage
from ...models.v1.prepuller import Node, PrepullerConfiguration
from ...storage.k8s import ContainerImage, K8sStorageClient
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
        self.logger.info("Querying K8s for image state on cluster nodes.")
        # Phase 1: interrogate K8s cluster for images on nodes.
        all_images_by_node = await self.k8s_client.get_image_data()
        # Phase 2: construct node objects from image data.
        nodes = self._make_nodes_from_image_data(all_images_by_node)
        # Phase 3: get the state of images on those nodes.
        images = self._construct_current_image_state(all_images_by_node)
        # Phase 4: update persistent state.
        self.state.set_images(images)
        self.state.set_nodes(nodes)
        self.state.update_k8s_check_time()
        self.logger.info("K8s query complete.")

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
        for node in images:
            for c in images[node]:
                path = self._extract_path_from_container(c)
                img_name = path.split("/")[-1]
                if img_name == name:
                    if node not in r:
                        r[node] = list()
                    t = copy(c)
                    r[node].append(t)
        return r

    def _extract_path_from_container(self, c: ContainerImage) -> str:
        return extract_path_from_image_ref(c.names[0])

    async def run_prepull_image(self, image: str, nodes: List[str]) -> None:
        pass

    def create_prepuller_pod_spec(
        self,
        image: str,
        node: str,
    ) -> V1PodSpec:
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
        return V1PodSpec(
            containers=[
                V1Container(
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
        spec = self.create_prepuller_pod_spec(image=image, node=node)
        await self.k8s_client.create_pod(
            name=name,
            namespace=namespace,
            pod=spec,
        )
