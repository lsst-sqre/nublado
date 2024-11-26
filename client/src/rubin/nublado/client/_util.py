"""Utility class and functions for Nublado client."""

import json
from dataclasses import dataclass

__all__ = [
    "CellSource",
    "normalize_source",
    "source_list_by_cell",
    "source_string_by_cell",
]


@dataclass
class CellSource:
    """Each cell has an ID, and its number is simply which cell it is
    (starting from 0).  The sources will be a list of strings.
    """

    cell_id: str
    cell_number: int
    source: list[str]


def normalize_source(notebook: str) -> str:
    """Extract and concatenate all the source cells from a notebook.

    Parameters
    ----------
    notebook
        The text of the notebook file.

    Returns
    -------
    str
       All non-empty source lines as a single Python string (with newline
    as the line separator).

    Notes
    -----
    This will give you the sequence of Python statements you would run if
    you executed each cell of the notebook in order if you merged all the
    code cells together.  This is how we generate cache keys for the
    ``run_notebook_via_rsp_extension()`` method (for purposes of mocking
    its responses).

    All lines will end with a newline, except for the very last one.

    Note that this doesn't necessarily give you the same output as if you ran
    the notebook, as the last statement in a cell is executed and the results
    displayed to the user in a notebook environment.

    """
    return "\n".join(
        [
            x.rstrip("\n")
            for x in source_string_by_cell(notebook)
            if x.rstrip("\n")
        ]
    )


def source_string_by_cell(notebook: str) -> list[str]:
    """Extract each cell source to a single string.

    Parameters
    ----------
    notebook
        The text of the notebook file.

    Returns
    -------
    list[str]
       A list of all non-empty source lines in a cell as a single Python
    string.  Each cell's source lines (with newline as the line separator) will
    be a separate item of the returned list.
    """
    src_list = source_list_by_cell(notebook)
    return ["\n".join(x.source) for x in src_list]


def source_list_by_cell(notebook: str) -> list[CellSource]:
    """Extract all non-empty "code" cells' "source" entry.  Attach the
    cell ID and the sequence number of the cell (one-indexed); each cell's
    source will be a list of strings.  This is encapsulated in a CellSource
    object.

    Parameters
    ----------
    notebook
        The notebook text.

    Returns
    -------
    list[CellSource]
       Source entries.
    """
    obj = json.loads(notebook)
    retval: list[CellSource] = []
    for idx, cell in list(enumerate(obj["cells"])):
        if cell["cell_type"] == "code" and "source" in cell and cell["source"]:
            retval.append(
                CellSource(
                    cell_id=cell["id"],
                    source=cell["source"],
                    cell_number=idx + 1,
                )
            )
    return retval
