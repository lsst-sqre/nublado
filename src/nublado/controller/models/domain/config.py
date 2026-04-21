"""Models for the JupyterLab UI configuration state."""

from dataclasses import asdict, dataclass

# Note that all of these, even when they duplicate something that's already
# present in the Lab definition, are defined as simple dataclasses with
# only primitive types representable in JSON.  That is because this model
# is designed to be directly decodable into a Javascript object for consumption
# by the JupyterLab UI.  Thus file paths are simply strings, not pathlib.Path
# objects, URLs are also just strings, and the UI resources are not borrowed
# from the Lab models.


@dataclass
class UIImageSpecification:
    """Description of Lab container image."""

    description: str
    digest: str
    spec: str


@dataclass
class UIContainerResource:
    """Description of container resources, used to construct UI."""

    cpu: float
    memory: int


@dataclass
class UIResources:
    """Limits and requests for the container, used to construct UI."""

    limits: UIContainerResource
    requests: UIContainerResource


type UIConfigPrimitive = dict[
    str, str | bool | dict[str, str | dict[str, int | float]]
]
"""Representation of UI config object as primitive types suitable for direct
conversion to JSON."""


@dataclass
class UIConfig:
    """Configuration state used by JupyterLab front-end."""

    container_size: str
    debug: bool
    enable_query_menu: bool
    enable_tutorials_menu: bool
    file_browser_root: str
    home_relative_to_file_browser_root: str
    image: UIImageSpecification
    jupyterlab_config_dir: str
    repertoire_base_url: str
    reset_user_env: bool
    resources: UIResources
    runtime_mounts_dir: str
    statusbar: str

    def to_dict(self) -> UIConfigPrimitive:
        """Primitive (JSON-suitable) representation of UI config object.

        Returns
        -------
        UIConfigPrimitive
            Primitive (JSON-suitable) representation of UI config object.
        """
        return asdict(self)
