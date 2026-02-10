"""Tests for startup object."""

import configparser
import errno
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pyfakefs.fake_filesystem import FakeFilesystem
from safir.testing.data import Data

from nublado.startup.services.credentials import CredentialManager
from nublado.startup.services.dask import DaskConfigurator
from nublado.startup.services.environment import EnvironmentConfigurator
from nublado.startup.services.homedir import HomedirManager
from nublado.startup.services.preparer import Preparer
from nublado.startup.utils import (
    get_digest,
    get_jupyterlab_config_dir,
    get_runtime_mounts_dir,
)


@pytest.mark.usefixtures("rsp_fs")
def test_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    preparer = Preparer()
    assert not preparer._debug
    monkeypatch.setenv("DEBUG", "1")
    preparer = Preparer()
    assert preparer._debug


def test_set_tmpdir(
    rsp_fs: FakeFilesystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Happy path.
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["TMPDIR"].endswith("/scratch/hambone/tmp")

    # Exists, but it's not a directory
    scratch_path = Path("/scratch/hambone/tmp")
    scratch_path.rmdir()
    rsp_fs.create_file(scratch_path)
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert "TMPDIR" not in em._env
    scratch_path.unlink()

    # Pre-set TMPDIR.
    monkeypatch.setenv("TMPDIR", "/preset")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert "TMPDIR" not in em._env
    monkeypatch.delenv("TMPDIR")

    # Can't write to scratch dir
    monkeypatch.setenv("SCRATCH_PATH", "/nonexistent/scratch")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert "TMPDIR" not in em._env


def test_set_butler_cache(
    rsp_fs: FakeFilesystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_v = "DAF_BUTLER_CACHE_DIRECTORY"

    # Happy path.
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env[env_v].endswith("/scratch/hambone/butler_cache")

    # Exists, but it's not a directory
    dbc = Path("/scratch/hambone/butler_cache")
    dbc.rmdir()
    rsp_fs.create_file(dbc)
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env[env_v] == "/tmp/butler_cache"
    dbc.unlink()

    # Pre-set DAF_BUTLER_CACHE_DIR.
    monkeypatch.setenv(env_v, "/preset")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert env_v not in pr._env


@pytest.mark.usefixtures("rsp_fs")
def test_cpu_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["CPU_LIMIT"] == "1"

    # We need a new Preparer each time because the environment configurator
    # modifies the environment dict in place.
    monkeypatch.setenv("CPU_LIMIT", "NaN")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["CPU_COUNT"] == "1"
    monkeypatch.setenv("CPU_LIMIT", "0.1")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["GOTO_NUM_THREADS"] == "1"
    monkeypatch.setenv("CPU_LIMIT", "3.1")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["MKL_DOMAIN_NUM_THREADS"] == "3"
    monkeypatch.setenv("CPU_LIMIT", "14")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["MPI_NUM_THREADS"] == "14"


def test_get_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUPYTER_IMAGE_SPEC", "sciplat-lab@sha256:abcde")
    digest = get_digest()
    assert digest == "abcde"


@pytest.mark.usefixtures("rsp_fs")
def test_expand_panda_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANDA_CONFIG_ROOT", "~")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["PANDA_CONFIG_ROOT"] == os.environ["NUBLADO_HOME"]
    monkeypatch.setenv("PANDA_CONFIG_ROOT", "~hambone")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["PANDA_CONFIG_ROOT"] == os.environ["NUBLADO_HOME"]
    monkeypatch.setenv("PANDA_CONFIG_ROOT", "~hambone/")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["PANDA_CONFIG_ROOT"] == os.environ["NUBLADO_HOME"]
    monkeypatch.setenv("PANDA_CONFIG_ROOT", "~whoopsi")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert "PANDA_CONFIG_ROOT" not in em._env
    monkeypatch.setenv("PANDA_CONFIG_ROOT", "/etc/panda")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert "PANDA_CONFIG_ROOT" not in em._env
    monkeypatch.setenv("PANDA_CONFIG_ROOT", "~/bar")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["PANDA_CONFIG_ROOT"] == (
        str(Path(os.environ["NUBLADO_HOME"]) / "bar")
    )


@pytest.mark.usefixtures("rsp_fs")
def test_jupyter_prefer_env_path() -> None:
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["JUPYTER_PREFER_ENV_PATH"] == "no"


@pytest.mark.usefixtures("rsp_fs")
def test_set_butler_credential_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/etc/secret/aws.creds")
    monkeypatch.setenv("PGPASSFILE", "/etc/secret/pgpass")
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    assert em._env["AWS_SHARED_CREDENTIALS_FILE"] == str(
        pr._home / ".lsst" / "aws.creds"
    )
    assert (
        pr._env["ORIG_AWS_SHARED_CREDENTIALS_FILE"] == "/etc/secret/aws.creds"
    )
    assert pr._env["PGPASSFILE"] == str(pr._home / ".lsst" / "pgpass")
    assert pr._env["ORIG_PGPASSFILE"] == "/etc/secret/pgpass"


def test_busted_homedir(
    rsp_fs: FakeFilesystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    rsp_fs.set_disk_usage(100000)
    pr = Preparer()
    pr.prepare()
    assert pr._broken
    assert pr._env["ABNORMAL_STARTUP"] == "TRUE"
    assert pr._env["ABNORMAL_STARTUP_ERRNO"] in (
        str(errno.EDQUOT),
        str(errno.ENOSPC),
    )
    pr._clear_abnormal_startup()
    assert pr._broken is not True


#
# File manipulation tests
#


@pytest.mark.usefixtures("rsp_fs")
def test_create_credential_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_dir = get_runtime_mounts_dir() / "secrets"
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(secret_dir / "aws-credentials.ini")
    )
    monkeypatch.setenv(
        "PGPASSFILE", str(secret_dir / "postgres-credentials.txt")
    )
    cred_dir = Path(os.environ["NUBLADO_HOME"]) / ".lsst"
    assert cred_dir.exists()
    shutil.rmtree(cred_dir)
    assert not cred_dir.exists()
    pr = Preparer()
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    cm = CredentialManager(env=em._env, logger=pr._logger)
    assert not cred_dir.exists()

    cm.copy_butler_credentials()
    assert cred_dir.exists()


@pytest.mark.usefixtures("rsp_fs")
def test_copy_butler_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_dir = get_runtime_mounts_dir() / "secrets"
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(secret_dir / "aws-credentials.ini")
    )
    monkeypatch.setenv(
        "PGPASSFILE", str(secret_dir / "postgres-credentials.txt")
    )
    pr = Preparer()
    pg = pr._home / ".lsst" / "postgres-credentials.txt"
    lines = pg.read_text().splitlines()
    aws = pr._home / ".lsst" / "aws-credentials.ini"
    for line in lines:
        if line.startswith("127.0.0.1:5432:db01:postgres:"):
            assert line.rsplit(":", maxsplit=1)[1] == "gets_overwritten"
        if line.startswith("127.0.0.1:5532:db02:postgres:"):
            assert line.rsplit(":", maxsplit=1)[1] == "should_stay"
    cp = configparser.ConfigParser()
    cp.read(str(aws))
    assert set(cp.sections()) == {"default", "tertiary"}
    assert cp["default"]["aws_secret_access_key"] == "gets_overwritten"
    assert cp["tertiary"]["aws_secret_access_key"] == "key03"
    em = EnvironmentConfigurator(env=pr._env, logger=pr._logger)
    em.configure_env()
    cm = CredentialManager(env=em._env, logger=pr._logger)
    cm.copy_butler_credentials()
    lines = pg.read_text().splitlines()
    aws = pr._home / ".lsst" / "aws-credentials.ini"
    for line in lines:
        if line.startswith("127.0.0.1:5432:db01:postgres:"):
            assert line.rsplit(":", maxsplit=1)[1] == "s33kr1t"
        if line.startswith("127.0.0.1:5532:db02:postgres:"):
            assert line.rsplit(":", maxsplit=1)[1] == "should_stay"
    cp = configparser.ConfigParser()
    cp.read(str(aws))
    assert set(cp.sections()) == {"default", "secondary", "tertiary"}
    assert cp["default"]["aws_secret_access_key"] == "key01"
    assert cp["secondary"]["aws_secret_access_key"] == "key02"
    assert cp["tertiary"]["aws_secret_access_key"] == "key03"


@pytest.mark.usefixtures("rsp_fs")
def test_dask_config() -> None:
    newlink = "{JUPYTERHUB_PUBLIC_URL}proxy/{port}/status"

    # First, just see if we create the default proxy settings.
    pr = Preparer()
    dm = DaskConfigurator(home=pr._home, logger=pr._logger)
    dask_dir = dm._home / ".config" / "dask"
    assert not dask_dir.exists()
    dm.setup_dask()
    assert dask_dir.exists()
    def_file = dask_dir / "dashboard.yaml"
    assert def_file.exists()
    obj = yaml.safe_load(def_file.read_text())
    assert obj["distributed"]["dashboard"]["link"] == newlink

    def_file.unlink()

    # Now test that we convert an old-style one to a user-domain config
    old_file = dask_dir / "lsst_dask.yml"
    assert not old_file.exists()

    obj["distributed"]["dashboard"]["link"] = (
        "{EXTERNAL_INSTANCE_URL}{JUPYTERHUB_SERVICE_PREFIX}proxy/{port}/status"
    )
    old_file.write_text(yaml.dump(obj, default_flow_style=False))

    assert not def_file.exists()
    assert old_file.exists()

    dm.setup_dask()  # Should replace the text.
    obj = yaml.safe_load(old_file.read_text())
    assert obj["distributed"]["dashboard"]["link"] == newlink

    old_file.unlink()
    assert not old_file.exists()

    # Test that we remove empty dict keys
    nullobj = {"key1": {"key2": {"key3": None}}}
    assert dm._flense_dict(nullobj) is None

    fl_file = dask_dir / "flense.yaml"
    assert not fl_file.exists()

    fl_file.write_text(yaml.dump(nullobj, default_flow_style=False))
    assert fl_file.exists()

    cm_file = dask_dir / "Comment.yaml"
    assert not cm_file.exists()
    cm_file.write_text("# Nothing but commentary\n")
    assert cm_file.exists()

    assert not def_file.exists()

    # This should create the defaults, and should remove the flensed
    # config and the only-comments file.
    dm.setup_dask()
    assert not fl_file.exists()
    assert not cm_file.exists()
    assert def_file.exists()

    # Test that we created a backup of the null file and the commentary
    fl_bk = dask_dir.glob("flense.yaml.*")
    assert len(list(fl_bk)) == 1
    cm_bk = dask_dir.glob("Comment.yaml.*")
    assert len(list(cm_bk)) == 1


@pytest.mark.usefixtures("rsp_fs")
def test_copy_logging_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Preparer()
    pfile = (
        pr._home / ".ipython" / "profile_default" / "startup" / "20-logging.py"
    )
    assert not pfile.exists()
    pfile.parent.mkdir(parents=True)
    hm = HomedirManager(env=pr._env, home=pr._home, logger=pr._logger)
    hm._copy_logging_profile()
    assert pfile.exists()
    h_contents = pfile.read_text()
    sfile = get_jupyterlab_config_dir() / "etc" / "20-logging.py"
    assert sfile.exists()
    s_contents = sfile.read_text()
    assert s_contents == h_contents
    h_contents += "\n# Locally modified\n"
    pfile.write_text(h_contents)
    hm._copy_logging_profile()
    new_contents = pfile.read_text()
    assert new_contents == h_contents
    assert new_contents != s_contents


@pytest.mark.usefixtures("rsp_fs")
def test_copy_dircolors(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Preparer()
    assert not (pr._home / ".dir_colors").exists()
    hm = HomedirManager(env=pr._env, home=pr._home, logger=pr._logger)
    hm._copy_dircolors()
    assert (pr._home / ".dir_colors").exists()


@pytest.mark.usefixtures("rsp_fs")
def test_copy_etc_skel(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Preparer()
    assert not (pr._home / ".gitconfig").exists()
    assert not (pr._home / ".pythonrc").exists()
    prc = Path("/etc/skel/.pythonrc").read_text()
    prc += "\n# Local mods\n"
    (pr._home / ".pythonrc").write_text(prc)
    hm = HomedirManager(env=pr._env, home=pr._home, logger=pr._logger)
    hm._copy_etc_skel()
    assert (pr._home / ".gitconfig").exists()
    sgc = Path("/etc/skel/.gitconfig").read_text()
    lgc = (pr._home / ".gitconfig").read_text()
    assert sgc == lgc
    src = Path("/etc/skel/.pythonrc").read_text()
    lrc = (pr._home / ".pythonrc").read_text()
    assert src != lrc
    assert (pr._home / "notebooks" / ".user_setups").exists()


@pytest.mark.usefixtures("rsp_fs")
def test_relocate_user_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESET_USER_ENV", "1")
    pr = Preparer()
    assert not (pr._home / ".local").exists()
    assert not (pr._home / "notebooks" / ".user_setups").exists()
    (pr._home / ".local").mkdir()
    (pr._home / ".local" / "foo").write_text("bar")
    (pr._home / "notebooks").mkdir()
    (pr._home / "notebooks" / ".user_setups").write_text("#!/bin/sh\n")
    pr._relocate_user_environment_if_requested()
    assert not (pr._home / ".local").exists()
    assert not (pr._home / "notebooks" / ".user_setups").exists()
    reloc = next(iter((pr._home).glob(".user_env.*")))
    assert (reloc / "local" / "foo").read_text() == "bar"
    assert (reloc / "notebooks" / "user_setups").read_text() == "#!/bin/sh\n"


@pytest.mark.usefixtures("rsp_fs")
def test_setup_gitlfs(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Preparer()
    hm = HomedirManager(env=pr._env, home=pr._home, logger=pr._logger)
    assert not hm._check_for_git_lfs()
    with patch.object(subprocess, "run") as mock:
        hm._setup_gitlfs()
        assert mock.call_count == 1
        gitconfig_path = pr._home / ".gitconfig"
        gitconfig_path.write_text('[filter "lfs"]\n')
    assert hm._check_for_git_lfs()


#
# Interactive-mode-only tests
#


@pytest.mark.usefixtures("rsp_fs")
def test_increase_log_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Preparer()
    settings = (
        pr._home
        / ".jupyter"
        / "lab"
        / "user-settings"
        / "@jupyterlab"
        / "notebook-extension"
        / "tracker.jupyterlab.settings"
    )
    assert not settings.exists()
    hm = HomedirManager(env=pr._env, home=pr._home, logger=pr._logger)
    hm._increase_log_limit()
    assert settings.exists()
    with settings.open() as f:
        obj = json.load(f)
    assert obj["maxNumberOutputs"] >= 10000


@pytest.mark.usefixtures("rsp_fs")
def test_manage_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    ctr_file = get_runtime_mounts_dir() / "secrets" / "token"

    # Save the token
    assert ctr_file.exists()
    token = ctr_file.read_text()

    # Remove the token file and ensure the fallback to the environment works.
    monkeypatch.setenv("ACCESS_TOKEN", token)
    ctr_file.unlink()
    assert not ctr_file.exists()
    pr = Preparer()
    tfile = pr._home / ".access_token"
    assert not tfile.exists()
    hm = HomedirManager(env=pr._env, home=pr._home, logger=pr._logger)
    hm._manage_access_token()
    assert tfile.exists()
    assert tfile.read_text() == token
    tfile.unlink()

    # Put the token back in its expected location and make sure it's copied.
    monkeypatch.delenv("ACCESS_TOKEN")
    ctr_file.write_text(token)
    assert ctr_file.exists()
    assert not tfile.exists()
    hm._manage_access_token()
    assert tfile.exists()
    assert tfile.read_text() == token


@pytest.mark.usefixtures("rsp_fs")
def test_startup_files(data: Data) -> None:
    pr = Preparer()
    with patch.object(subprocess, "run"):
        pr.prepare()
    env_file = Path("/etc/nublado/startup/env.json")
    arg_file = Path("/etc/nublado/startup/args.json")
    env = json.loads(env_file.read_text())
    args = json.loads(arg_file.read_text())

    data.assert_json_matches(env, "startup/output/env")
    data.assert_json_matches(args, "startup/output/args")
