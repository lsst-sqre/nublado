from pathlib import Path


def check_file(inp: str, fname: Path) -> None:
    """Give it a string and a file path; if the contents of the file match
    the string, nothing happens; if they do not, the assert fails.

    Very handy for a document-driven test suite."""
    with open(fname) as f:
        expected = f.read()
    assert inp == expected
