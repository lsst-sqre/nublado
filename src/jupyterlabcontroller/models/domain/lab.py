from dataclasses import dataclass

from ...storage.k8s import Volume, VolumeMount


@dataclass
class LabVolumeContainer:
    volume: Volume
    volume_mount: VolumeMount
