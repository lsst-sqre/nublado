"""Function for filtering out architecture-specific tags."""

_ARCHITECTURES = ["arm64", "amd64"]

__all__ = ["filter_arch_tags"]


def filter_arch_tags(tags: list[str]) -> list[str]:
    """Architecture-specific tags end in "-{arch}".

    If we encounter one of those, and there is a tag that matches it up
    to the suffix, we discard the architecture-specific tag.
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
