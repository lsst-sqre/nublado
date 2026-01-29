"""Tests for the JuypterLab launcher."""

import json
import os
from unittest.mock import call, patch

from pyfakefs.fake_filesystem import FakeFilesystem

from rubin.nublado.startup import launch_lab


def test_launch(fs: FakeFilesystem) -> None:
    extra_env = {"ONE_VAR": "something", "TWO_VAR": "something-else"}
    command = ["jupyterhub-singleuser", "--ip=0.0.0.0", "--port=8888"]

    fs.create_file(
        "/etc/nublado/startup/env.json",
        contents=json.dumps(extra_env),
        create_missing_dirs=True,
    )
    fs.create_file(
        "/etc/nublado/startup/args.json", contents=json.dumps(command)
    )

    expected_env = os.environ.copy()
    expected_env.update(extra_env)
    with patch.object(os, "execvpe") as mock:
        launch_lab()
        assert mock.call_args_list == [
            call(command[0], command, env=expected_env)
        ]
