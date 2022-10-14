from kubernetes_asyncio.client.models import V1ObjectMeta

from ..runtime.std import std_annotations, std_labels


def get_std_metadata(name: str) -> V1ObjectMeta:
    return V1ObjectMeta(
        name=name, labels=std_labels(), annotations=std_annotations()
    )
