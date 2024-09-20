"""Utility functions for Nublado client."""

import json
from enum import Enum

__all__ = [
    "normalize_source",
    "source_string_by_cell",
    "source_list_by_cell",
    "notebook_to_disk_form",
    "notebook_to_api_form",
]


class NotebookForm(Enum):
    DISK = "disk"
    API = "api"


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

    Notes
    -----
    This is what the contents API returns, although the text of the notebook
    on disk will have each source line as its own entry within a list of
    strings.  So we will convert it to API form first and then return the
    source item from each cell.
    """
    notebook = notebook_to_api_form(notebook)
    obj = json.loads(notebook)
    return [
        x["source"]
        for x in obj["cells"]
        if x["cell_type"] == "code" and "source" in x and x["source"]
    ]


def source_list_by_cell(notebook: str) -> list[list[str]]:
    """Extract all non-empty "code" cells' "source" entry as a list of strings.

    Parameters
    ----------
    notebook
        The notebook text, or the results of the Contents API.

    Returns
    -------
    list[str]
       Source entries.

    Notes
    -----
    In the notebook, "source" is a list of strings.  In the Contents API, it's
    a single string.  So we will convert the notebook to disk form, and return
    the list of lists.
    """
    notebook = notebook_to_disk_form(notebook)
    obj = json.loads(notebook)
    return [
        x["source"]
        for x in obj["cells"]
        if x["cell_type"] == "code" and "source" in x and x["source"]
    ]


def notebook_to_disk_form(notebook: str) -> str:
    return _transform_notebook(notebook, NotebookForm.DISK)


def notebook_to_api_form(notebook: str) -> str:
    return _transform_notebook(notebook, NotebookForm.API)


def _transform_notebook(notebook: str, form: NotebookForm) -> str:
    obj = json.loads(notebook)
    cells = obj["cells"]
    # Transform each cell's source as needed
    for cell in cells:
        if cell["cell_type"] != "code":
            continue
        if "source" not in cell or not cell["source"]:
            continue
        src = cell["source"]
        if (isinstance(src, str) and form == NotebookForm.API) or (
            isinstance(src, list) and form == NotebookForm.DISK
        ):
            # Already in the correct form
            continue
        if form == NotebookForm.API:
            # Turn source into a newline-separated string
            cell["source"] = _list_to_string(src)
            continue
        # If we got this far, we need to turn the source into a list, where
        # all items but the list end in a single newline.
        cell["source"] = _string_to_list(src)
    return json.dumps(obj)


def _list_to_string(src: list[str]) -> str:
    copy_list: list[str] = []
    for src_line in src:
        copy_line = src_line.rstrip("\n")
        if copy_line:
            copy_list.append(copy_line)
    return "\n".join(copy_list)


def _string_to_list(src: str) -> list[str]:
    src_list = src.split("\n")
    copy_list: list[str] = []
    for src_line in src_list:
        copy_line = src_line.rstrip("\n")
        if copy_line:
            copy_line += "\n"
            copy_list.append(copy_line)
    if copy_list:
        copy_list[-1].rstrip("\n")
    return copy_list
