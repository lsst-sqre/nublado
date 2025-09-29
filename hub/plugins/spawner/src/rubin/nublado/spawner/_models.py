"""Models for the Nublado JupyterHub spawner class."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from httpx_sse import ServerSentEvent


class LabStatus(StrEnum):
    """Possible status conditions of a user's pod per the lab controller.

    This is not directly equivalent to pod phases. It is instead intended to
    capture the status of the lab from an infrastructure standpoint,
    reflecting the current intent of the controller. Most notably, labs that
    have stopped running for any reason (failure or success) use the
    terminated status. The failed status is reserved for failed Kubernetes
    operations or missing or invalid Kubernetes objects.

    Keep this in sync with the status values reported by the status endpoint
    of the lab controller.
    """

    PENDING = "pending"
    RUNNING = "running"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SpawnEvent:
    """JupyterHub spawning event."""

    progress: int
    """Percentage of progress, from 0 to 100."""

    message: str
    """Event description."""

    severity: str
    """Log message severity."""

    complete: bool = False
    """Whether the event indicated spawning is done."""

    failed: bool = False
    """Whether the event indicated spawning failed."""

    @classmethod
    def from_sse(cls, sse: ServerSentEvent, progress: int) -> SpawnEvent:
        """Convert from a server-sent event from the lab controller.

        Parameters
        ----------
        sse
            Event from the lab controller.
        progress
            Current progress percentage, if the event doesn't specify one.
        """
        try:
            data = sse.json()
            if not (set(data.keys()) <= {"message", "progress"}):
                raise ValueError("Invalid key in SSE data")
            if "progress" in data:
                progress = int(data["progress"])
                if progress < 0 or progress > 100:
                    raise ValueError(f"Invalid progress value {progress}")
        except Exception:
            data = {"message": sse.data}
        data["progress"] = progress

        if sse.event == "complete":
            data["progress"] = 75
            return cls(**data, severity="info", complete=True)
        elif sse.event in ("info", "error"):
            return cls(**data, severity=sse.event)
        elif sse.event == "failed":
            return cls(**data, severity="error", failed=True)
        else:
            return cls(**data, severity="unknown")

    def to_dict(self) -> dict[str, int | str]:
        """Convert to the dictionary expected by JupyterHub."""
        return {
            "progress": self.progress,
            "message": f"[{self.severity}] {self.message}",
        }
