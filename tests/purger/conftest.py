"""Pytest configuration and fixtures."""

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from nublado.purger.config import Config


def config(root: Path, relative_policy_file: str) -> Config:
    """Write a policy file and config file that reference real temp files."""
    scratch_dir = root / "scratch"
    scratch_foo_bar = scratch_dir / "foo" / "bar"

    # Load template policy file
    policy_file = (
        Path(__file__).parent.parent / "data" / "purger" / relative_policy_file
    )
    policy = yaml.safe_load(policy_file.read_text())

    # Change policy to point at fake root
    policy["directories"][0]["path"] = str(scratch_dir)
    policy["directories"][1]["path"] = str(scratch_foo_bar)

    new_policy_file = root / "policy.yaml"
    new_policy_file.write_text(yaml.dump(policy))

    # Write a new config file that points at the new policy document
    config_file = (
        Path(__file__).parent.parent / "data" / "purger" / "config.yaml"
    )
    config = yaml.safe_load(config_file.read_text())
    config["policyFile"] = str(new_policy_file)
    new_config_file = root / "config.yaml"
    new_config_file.write_text(yaml.dump(config))

    return Config.from_file(new_config_file)


@pytest.fixture
def fake_root() -> Iterator[Path]:
    with TemporaryDirectory() as td:
        contents = {
            "small": "hi",
            "medium": "Hello, world!",
            "large": "The quick brown fox jumped over the lazy dog.",
        }
        # Medium is "large" for "scratch" but "small" for "scratch/foo/bar".
        tp = Path(td)
        scratch_dir = tp / "scratch"
        foo_bar_dir = scratch_dir / "foo" / "bar"
        foo_bar_dir.mkdir(parents=True)
        for directory in (scratch_dir, foo_bar_dir):
            for sz, txt in contents.items():
                (directory / sz).write_text(txt)
        yield tp


@pytest.fixture
def purger_config(fake_root: Path) -> Config:
    return config(fake_root, "policy.yaml")


@pytest.fixture
def purger_config_small(fake_root: Path) -> Config:
    return config(fake_root, "policy_small.yaml")


@pytest.fixture
def purger_config_no_small(fake_root: Path) -> Config:
    return config(fake_root, "policy_no_small.yaml")


@pytest.fixture
def purger_config_low_ctime(fake_root: Path) -> Config:
    return config(fake_root, "policy_low_ctime.yaml")
