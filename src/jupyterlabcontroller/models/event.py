"""Event model for jupyterlab-controller."""

from sse_starlette import ServerSentEvent


# It's just a repackaged ServerSentEvent with a "sent" field glued on
class Event(ServerSentEvent):
    sent: bool = False

    def toSSE(self):
        return ServerSentEvent(data=self.data, event=self.event)


# Need validation on its type
