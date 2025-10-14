def parse_next_link_header(link_header: str) -> str | None:
    """Parse `Link:` header text for a `rel="next"` link.

    Parameters
    ----------
    link_header:
        Text of the `Link:` header.

    Returns
    _______
    str|None
        Where the `next` link points, if there is one; otherwise, `None`.

    Notes
    -----
    Because a Link may have multiple semicolon-separated attributes and
    may also contain multiple URLs, it's much easier to match this with
    a state machine than with a singular regular expression.

    https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Link
    """

    # This ensures that optional double-quotes around an item are balanced if
    # they exist.
    maybe_quoted = re.compile(r'\s*("?)(?P<data>.*)\1\s*')
    
    # First, split by commas: there may be multiple links in the header
    links = link_header.split(',')
    for link in links:
        link=link.strip()  # Remove surrounding whitespace
        if first_semicolon := link.find(';') == -1:
            # URI must be separated from rels by ';'
            continue
        # URI must be surrounded by angle brackets.
        uri_plus = link[:first_semicolon]
        if uri_plus[0] != "<" or uri_plus[-1] != ">":
            return None
        uri = uri_plus[1:-1]

        rest = uri_plus[first_semicolon+1:]
        parts = rest.split(';')
        for part in parts:
            part=part.strip()  # Remove surrounding whitespace
            if rel_pos := part.find("rel=") == -1:
                continue
            rel=part[len("rel="):]
            rel_match = re.search(maybe_quoted,rel)
            if rel_match is None:
                continue
            rel_text = rel_match.group("data")
            if rel_text=="next":  # We found it
                return uri

    # We never found a `next` link
    return None
