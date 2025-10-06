"""Function for filtering out architecture-specific tags."""

_ARCHITECTURES = ["arm64", "amd64"]

__all__ = ["filter_arch_tags"]


def filter_arch_tags(tags: list[str]) -> list[str]:
    """Architecture-specific tags end in "-{arch}".

    If we encounter one of those, and there is a tag that matches it up
    to the suffix, we discard the architecture-specific tag.
    """
    filtered: list[str] = []
    for tag in tags:
        arches = [f"-{x}" for x in _ARCHITECTURES]
        might_match = [tag.endswith(x) for x in arches]
        if not (any(might_match)):
            filtered.append(tag)
            continue
        base_tag: None | str = None
        for arch in arches:
            if tag.endswith(arch):
                base_tag = tag[: -len(arch)]
                break
        if base_tag is not None and base_tag not in tags:
            filtered.append(tag)
    return filtered
