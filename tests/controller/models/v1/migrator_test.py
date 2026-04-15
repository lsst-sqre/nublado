"""Test MigratorStatus exception handling."""

import datetime

import pytest

from nublado.controller.exceptions import (
    CopyError,
    CopyPermissionError,
    NoSourceUserDirectoryError,
    NoTargetUserDirectoryError,
)
from nublado.controller.models.v1.migrator import MigratorStatus


def test_migrator_status_exceptions() -> None:
    """Verify that MigratorStatus raises appropriate exceptions."""
    st = MigratorStatus(old_user="alice", new_user="bob")
    # start_time and running set
    st.raise_for_status()  # Does nothing
    st.running = False
    with pytest.raises(RuntimeError):
        st.raise_for_status()  # Not running, no exit code
    st.exit_code = 0
    with pytest.raises(RuntimeError):
        st.raise_for_status()  # Not running, no end time
    st.end_time = datetime.datetime.now(tz=datetime.UTC).isoformat()
    st.running = True
    with pytest.raises(RuntimeError):
        st.raise_for_status()  # Running but has exit code
    st.running = False
    st.exit_code = 3
    with pytest.raises(RuntimeError):
        st.raise_for_status()  # Unrecognized exit code
    st.exit_code = 4
    with pytest.raises(NoSourceUserDirectoryError):
        st.raise_for_status()
    st.exit_code = 5
    with pytest.raises(NoTargetUserDirectoryError):
        st.raise_for_status()
    st.exit_code = 6
    with pytest.raises(CopyError):
        st.raise_for_status()
    st.exit_code = 7
    with pytest.raises(CopyPermissionError):
        st.raise_for_status()
    st.start_time = st.end_time
    st.start_time = datetime.datetime.now(tz=datetime.UTC).isoformat()
    with pytest.raises(RuntimeError):
        st.raise_for_status()  # Start time after end time
