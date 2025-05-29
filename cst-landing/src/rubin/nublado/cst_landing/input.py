"""Convenience class and function for handling provisioner inputs."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProvisionerInput:
    """Convenience class for handling provisioner inputs."""

    source_files: list[Path]
    home_dir: Path
    dest_dir: Path
    debug: bool = False


def input_from_env() -> ProvisionerInput:
    """Construct input from environment and defaults."""
    debug = bool(os.getenv("DEBUG", ""))
    home_dir = Path(os.getenv("NUBLADO_HOME", "/nonexistent"))
    source_dir = Path(
        os.getenv(
            "CST_LANDING_PAGE_SRC_DIR",
            "/rubin/cst_repos/tutorial-notebooks-data/data",
        )
    )
    target_dir = Path(
        os.getenv("CST_LANDING_PAGE_TGT_DIR", "notebooks/tutorials")
    )
    filelist_str = os.getenv(
        "CST_LANDING_PAGE_FILES", "landing_page.md,logo_for_header.png"
    )
    filelist_list = filelist_str.split(",")
    source_files = [source_dir / x for x in filelist_list]
    dest_dir = home_dir / target_dir

    return ProvisionerInput(
        source_files=source_files,
        home_dir=home_dir,
        dest_dir=dest_dir,
        debug=debug,
    )
