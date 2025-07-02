"""Pytest configuration and fixtures."""

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from rubin.nublado.purger.config import Config
from rubin.nublado.purger.models.v1.policy import Policy


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
    scratch_dir = fake_root / "scratch"
    scratch_foo_bar = scratch_dir / "foo" / "bar"

    # Load template policy file
    policy_file = Path(__file__).parent / "support" / "policy.yaml"
    policy_doc = yaml.safe_load(policy_file.read_text())
    policy = Policy.model_validate(policy_doc)
    config_file = Path(__file__).parent / "support" / "config.yaml"
    config_doc = yaml.safe_load(config_file.read_text())
    config = Config.model_validate(config_doc)

    # Change policy to point at fake root
    policy.directories[0].path = scratch_dir
    policy.directories[1].path = scratch_foo_bar

    # Write out new policy document
    new_policy_dict = policy.to_dict()
    new_policy_doc = yaml.dump(new_policy_dict)
    new_policy_file = fake_root / "policy.yaml"
    new_policy_file.write_text(new_policy_doc)

    # Point config at new policy document
    config = Config()
    config.policy_file = new_policy_file

    # Write out new config
    new_config_dict = config.to_dict()
    new_config_doc = yaml.dump(new_config_dict)
    new_config_file = fake_root / "config.yaml"
    new_config_file.write_text(new_config_doc)

    return config
