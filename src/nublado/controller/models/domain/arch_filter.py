"""Functions for filtering out architecture-specific tags or images."""

from .rspimage import RSPImage

_ARCHITECTURES = ["arm64", "amd64"]

__all__ = ["filter_arch_images", "filter_arch_tags"]


def filter_arch_tags(tags: list[str]) -> list[str]:
    """Architecture-specific tags end in "-{arch}".

    If we encounter one of those, and there is a tag that matches it up
    to the suffix, we discard the architecture-specific tag.

    Parameters
    ----------
    tags
        Input tags.

    Returns
    -------
    list[str]
        Tags after architecture-specific filtering.

    Notes
    -----
    This function is only directly useful to the Docker driver, which works
    on tags. The GAR driver works on RSPImages instead; it relies on this
    function for its corresponding filter function (see below).
    """
    arches = [f"-{x}" for x in _ARCHITECTURES]
    tag_set = set(tags)  # O(1) lookup instead of O(n)
    filtered: list[str] = []

    for tag in tags:
        # Check if this is an arch-specific tag
        arch_suffix = next((a for a in arches if tag.endswith(a)), None)

        if arch_suffix is None:
            # Not arch-specific, always include
            filtered.append(tag)
        else:
            # Only include if base tag doesn't exist
            base_tag = tag[: -len(arch_suffix)]
            if base_tag not in tag_set:
                filtered.append(tag)

    return filtered


def filter_arch_images(images: list[RSPImage]) -> list[RSPImage]:
    """Architecture-specific tags end in "-{arch}".

    If we encounter an image with one of those, and there is an image in the
    list with tag that matches it up to the suffix, we discard the
    architecture-specific image.

    Parameters
    ----------
    images
        Input RSPImages.

    Returns
    -------
    list[RSPImage]
        Images after architecture-specific filtering.

    Notes
    -----
    This is necessary for the GAR driver, which works on RSPImages, as
    opposed to the Docker driver, which works on tags.

    We rely on the fact that dicts are insertion-ordered in Python 3.6 and
    later. This is basically a decorate-filter-undecorate function.
    """
    i_dict = {x.tag: x for x in images}
    tag_keys = list(i_dict.keys())
    filtered_keys = filter_arch_tags(tag_keys)
    o_dict = {x: i_dict[x] for x in filtered_keys}
    return list(o_dict.values())
