"""Optional context for exception reporting during code execution."""

from dataclasses import dataclass


@dataclass
class CodeContext:
    """Optional context for exception reporting during code execution."""

    image: str | None = None
    notebook: str | None = None
    path: str | None = None
    cell: str | None = None
    cell_number: str | None = None
    cell_source: str | None = None
    cell_line_number: str | None = None
    cell_line_source: str | None = None
