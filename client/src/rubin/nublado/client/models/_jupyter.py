from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JupyterOutput:
    """Output from a Jupyter lab kernel.

    Parsing WebSocket messages will result in a stream of these objects with
    partial output, ending in a final one with the ``done`` flag set.

    Note that there is some subtlety here: a notebook cell can either
    print its output (that is, write to stdout), or, in an executed notebook,
    the cell will display the last Python command run.

    These are currently represented by two unhandled message types,
    ``execute_result`` (which is the result of the last Python command run;
    this is analogous to what you get in the Pytheon REPL loop) and
    ``display_data``.  ``display_data`` would be what you get, for instance,
    when you ask Bokeh to show a figure: it's a bunch of Javascript that
    will be interpreted by your browser.

    The protocol is found at https://jupyter-client.readthedocs.io/en/latest/
    but what we want to use is half a layer above that.  We care what
    some messages on the various channels are, but not at all about the
    low-level implementation details of how those channels are established
    over ZMQ, for instance.
    """

    content: str
    """Partial output from code execution (may be empty)."""

    done: bool = False
    """Whether this indicates the end of execution."""


@dataclass(frozen=True, slots=True)
class SpawnProgressMessage:
    """A progress message from lab spawning."""

    progress: int
    """Percentage progress on spawning."""

    message: str
    """A progress message."""

    ready: bool
    """Whether the server is ready."""
