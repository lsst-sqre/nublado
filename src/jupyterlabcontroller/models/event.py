"""Event model for jupyterlab-controller."""

from sse_starlette import ServerSentEvent


# It's just a repackaged ServerSentEvent
class Event(ServerSentEvent):
    pass


# Need validation on its type
