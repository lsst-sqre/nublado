"""Interactive harness; will connect to each registry.

For this particular harness, you will need to have:

* GHCR_TOKEN set for GitHub Container Registry authentication
* DOCKERHUB_USER and DOCKERHUB_PASSWORD set for Docker Hub authentication
* already run `gcloud auth application-default login` to get Google
  Application Default credentials
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from rsp_reaper.config import Config
from rsp_reaper.services.reaper import BuckDharma

with TemporaryDirectory() as td:
    new_config = Path(td) / "config.yaml"
    support_dir = Path(__file__).parent.parent / "tests" / "support"
    config = yaml.safe_load((support_dir / "config.yaml").read_text())
    config["registries"][0]["inputFile"] = None
    config["registries"][1]["inputFile"] = None
    new_config.write_text(yaml.dump(config))

    cfg = Config.from_file(new_config)

    boc = BuckDharma(cfg)

    print("\nReaper application is in variable 'boc'")
    print("---------------------------------------\n")
