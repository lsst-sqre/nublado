"""Fixtures for inithome testing."""

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem, set_gid, set_uid


@dataclass
class User:
    homedir: Path
    uid: int
    gid: int


USERS = {
    "gsamsa": User(homedir=Path("/home/gsamsa"), uid=2247, gid=200),
    "josephk": User(
        homedir=Path("/home/j/josephk/nublado"), uid=63928, gid=63928
    ),
    "leni": User(homedir=Path("/home/leni"), uid=2000, gid=200),
    "grubach": User(homedir=Path("/home/grubach"), uid=9942, gid=500),
    "karl": User(homedir=Path("/home/karl"), uid=1088, gid=500),
    "huld": User(homedir=Path("/home/huld"), uid=4346, gid=4346),
    "burstner": User(homedir=Path("/home/burstner"), uid=7304, gid=7304),
}


@pytest.fixture
def privileged_fs(fs: FakeFilesystem) -> FakeFilesystem:
    # We do most of our work as "root"
    set_uid(0)
    set_gid(0)

    # Set up typical homedir structure
    fs.create_dir("/home", perm_bits=0o755)

    # Create a first-initial-then-name hierarchy for josephk
    fs.create_dir("/home/j", perm_bits=0o755)

    # Precreate directory for leni
    fs.create_dir(USERS["leni"].homedir, perm_bits=0o700)
    os.chown(
        USERS["leni"].homedir, uid=USERS["leni"].uid, gid=USERS["leni"].gid
    )

    # Create directory with wrong owner for grubach
    fs.create_dir(USERS["grubach"].homedir, perm_bits=0o700)
    os.chown(
        USERS["grubach"].homedir,
        uid=9 + USERS["grubach"].uid,
        gid=USERS["grubach"].gid,
    )

    # Create directory with wrong group for karl
    fs.create_dir(USERS["karl"].homedir, perm_bits=0o700)
    os.chown(
        USERS["karl"].homedir,
        uid=USERS["karl"].uid,
        gid=17 + USERS["karl"].gid,
    )

    # Create non-directory for huld
    fs.create_file(USERS["huld"].homedir, contents="huld")
    USERS["huld"].homedir.chmod(0o700)
    os.chown(
        USERS["huld"].homedir, uid=USERS["huld"].uid, gid=USERS["huld"].gid
    )

    # Create directory with wrong permissions for burstner
    fs.create_dir(USERS["burstner"].homedir, perm_bits=0o775)
    os.chown(
        USERS["burstner"].homedir,
        uid=USERS["burstner"].uid,
        gid=USERS["burstner"].gid,
    )

    return fs
