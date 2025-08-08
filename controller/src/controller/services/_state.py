"""State class used by both fileserver and fsadmin to track service
state.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

__all__ = ["ServiceState"]


@dataclass
class ServiceState:
    """State of the fsadmin environment."""

    running: bool
    """Whether the fsadmin container is running."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Lock to prevent two operations from happening at once."""

    in_progress: bool = False
    """Whether an operation is currently in progress."""

    last_modified: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC)
    )
    """Last time an operation was started or completed.

    This is required to prevent race conditions such as the following:

    #. New file server starts being created.
    #. Reconcile gathers information about the partially created lab and finds
       that it is incomplete.
    #. Reconcile deletes the file server objects created so far.
    #. File server creation finishes and then the file server doesn't work.
    #. Multiple users are trying to start or stop an fsadmin instance
       simultaneously.

    With this setting, reconcile can check if a file server operation has
    started or recently finished and skip the reconcile.
    """

    def modified_since(self, date: datetime) -> bool:
        """Whether the fsadmin pod has been modified since the given time.

        Any fsadmin instance that has a current in-progress operation is
        counted as modified.

        Parameters
        ----------
        date
            Reference time.

        Returns
        -------
        bool
            `True` if the internal last-modified time is after the provided
            time and no operation is in progress, `False` otherwise.
        """
        return bool(self.in_progress or self.last_modified > date)
