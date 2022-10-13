"""Event model for jupyterlab-controller."""

from sse_starlette import ServerSentEvent


# It's just a repackaged ServerSentEvent with a "sent" field glued on
class Event(ServerSentEvent):
    sent: bool = False


# Need validation on its type
