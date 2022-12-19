from dataclasses import dataclass

from kubernetes_asyncio.client.models import V1Volume, V1VolumeMount


@dataclass
class LabVolumeContainer:
    volume: V1Volume
    volume_mount: V1VolumeMount
