from dataclasses import dataclass
from typing import Optional

from .errors import EventError


@dataclass
class Event:
    data: str
    event_type: str
    # A server-sent event also has "id" and "retry" fields.  We're not
    # going to support these in this implementation.

    @classmethod
    def from_lines(self, inp: list[str]) -> Optional["Event"]:
        if not inp:
            # If we get two blanks in a row, we will send an empty list
            # as an input.
            return None
        current_type = ""
        databuffer = ""
        for line in inp:
            # Parse according to https://html.spec.whatwg.org/multipage/
            #  server-sent-events.html#event-stream-interpretation
            # line has already been stripped
            if line[0] == ":":  # That's a comment
                continue
            field = ""
            value = ""
            if ":" in line:
                field, value = line.split(":", 1)
                if value and value[0] == " ":
                    value = value[1:]  # The spec says, only remove one space.
            else:
                field = line
            # Value remains the empty string
            if field == "event":
                if current_type and current_type != value:
                    raise EventError(
                        f"Received multiple event types '{value}' and "
                        + f"'{current_type}' for a single event's data"
                    )
                current_type = value
            elif field == "data":
                # Accumulate data into buffer
                databuffer += value + "\n"
            else:
                # Ignore the line.  If we were doing a full implementation,
                # we would use the "id" and "retry" fields.  But we're not.
                continue
        if not current_type:
            raise EventError(
                f"Received event data '{databuffer}' but do not know "
                + "event type"
            )
        return Event(event_type=current_type, data=databuffer)

    def progress(self) -> Optional[int]:
        if self.event_type != "progress":
            return None
        return int(self.data)

    def message(self) -> Optional[str]:
        if self.event_type not in ("info", "error", "failed"):
            return None
        return self.data
