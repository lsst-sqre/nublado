from dataclasses import dataclass


@dataclass
class FormSize:
    name: str
    cpu: str
    memory: str

    @property
    def description(self) -> str:
        return f"{self.name} ({self.cpu} CPU, {self.memory } RAM)"


@dataclass(frozen=True, slots=True)
class MenuImage:
    reference: str
    """Docker reference."""

    name: str
    """Human-readable name."""


@dataclass(frozen=True, slots=True)
class MenuImages:
    menu: list[MenuImage]
    """Images that should appear as regular menu choices."""

    dropdown: list[MenuImage]
    """Extra images to populate the dropdown."""