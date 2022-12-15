"""Utility functions for the prepuller."""


def extract_path_from_image_ref(ref: str) -> str:
    # Remove the specifier from either a digest or a tagged image
    if "@sha256:" in ref:
        # Everything before the '@'
        untagged = ref.split("@")[0]
    else:
        # Everything before the last ':'
        untagged = ":".join(ref.split(":")[:-1])
    return untagged
