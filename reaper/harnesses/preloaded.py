"""Interactive harness using preloaded data."""

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from rsp_reaper.config import Config
from rsp_reaper.services.reaper import BuckDharma

with TemporaryDirectory() as td:
    new_config = Path(td) / "config.yaml"
    support_dir = Path(__file__).parent.parent / "tests" / "support"
    config = yaml.safe_load((support_dir / "config.yaml").read_text())
    config["registries"][0]["input_file"] = str(support_dir / "gar.contents.json")
    config["registries"][1]["input_file"] = str(support_dir / "ghcr.io.contents.json")
    config["registries"][2]["input_file"] = str(support_dir / "docker.io.contents.json")
    new_config.write_text(yaml.dump(config))

    cfg = Config.from_file(new_config)

    boc = BuckDharma(cfg)

    print("\nReaper application is in variable 'boc'")
    print("---------------------------------------\n")
