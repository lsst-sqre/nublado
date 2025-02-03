"""Interactive harness using preloaded data."""

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from reaper.config import Config
from reaper.services.reaper import BuckDharma

with TemporaryDirectory() as td:
    new_config = Path(td) / "config-3.yaml"
    support_dir = Path(__file__).parent.parent / "tests" / "support"
    config = yaml.safe_load((support_dir / "config-3.yaml").read_text())
    config["registries"][0]["inputFile"] = str(support_dir / "gar.contents.json")
    config["registries"][1]["inputFile"] = str(support_dir / "ghcr.io.contents.json")
    config["registries"][2]["inputFile"] = str(support_dir / "docker.io.contents.json")
    cfg_text = yaml.dump(config)
    new_config.write_text(yaml.dump(config))

    cfg = Config.from_file(new_config)

    boc = BuckDharma(cfg)

    print("\nReaper application is in variable 'boc'")
    print("---------------------------------------\n")
