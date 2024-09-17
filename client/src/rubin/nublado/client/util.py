"""Utility functions for Nublado client."""

import json

__all__ = [
    "normalize_source",
    "normalize_source_by_cell",
    "extract_source_by_cell",
]


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
            for x in normalize_source_by_cell(notebook)
            if x.rstrip("\n")
        ]
    )


def normalize_source_by_cell(notebook: str) -> list[str]:
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
    return [
        "\n".join(
            [
                x.rstrip("\n")
                for y in extract_source_by_cell(notebook)
                for x in y
                if x.rstrip("\n")
            ]
        )
    ]


def extract_source_by_cell(notebook: str) -> list[list[str]]:
    """Extract all non-empty "code" cells' "source" lines as a list of strings.

    Parameters
    ----------
    notebook
        The text of the notebook file.

    Returns
    -------
    list[list[str]]
       Source lines
    """
    obj = json.loads(notebook)
    return [
        x["source"]
        for x in obj["cells"]
        if x["cell_type"] == "code" and x["source"]
    ]
