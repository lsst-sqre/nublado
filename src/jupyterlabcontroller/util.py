"""General utility functions."""

import datetime

from safir.datetime import current_datetime


def stale(check_time: datetime.datetime, max_age: datetime.timedelta) -> bool:
    return current_datetime() - max_age > check_time


def deslashify(data: str) -> str:
    return data.replace("/", "_._")


def slashify(data: str) -> str:
    return data.replace("_._", "/")


# Dashify is needed to turn, e.g. "latest_weekly" into the required
# "latest-weekly" per sqr-066.


def dashify(item: str) -> str:
    return item.replace("_", "-")


def image_to_podname(image: str) -> str:
    short_name = (image.split(":")[0]).split("/")[-1]
    tag = dashify((image.split(":")[1]).split("@")[0])
    if not short_name or not tag:
        raise RuntimeError(
            "At least one of short_name '{short_name}' and tag '{tag}' empty!"
        )
    podname = f"{short_name}-{tag}"
    if "@sha256-" in podname:
        podname = podname.replace("@sha256-", "-sha256-")
    return podname


def extract_untagged_path_from_image_ref(ref: str) -> str:
    # Remove the digest if it's there
    if "@sha256:" in ref:
        # Everything before the '@'
        undigested = ref.split("@")[0]
    else:
        # it's the whole thing
        undigested = ref
    if ":" in undigested:
        untagged = undigested.split(":")[0]
    else:
        untagged = undigested
    return untagged


def remove_tag_from_image_ref(ref: str) -> str:
    if "@sha256:" in ref:
        digest = ref.split("@")[1]
        tagged = ref.split("@")[0]
        if ":" in tagged:
            untagged_loc = tagged.split(":")[0]
        else:
            untagged_loc = tagged
        return f"{untagged_loc}@{digest}"
    else:
        raise RuntimeError(f"Ref {ref} has no digest")


def str_to_bool(inp: str) -> bool:
    """This is OK at detecting False, and everything else is True"""
    inpl = inp.lower()
    if inpl in ("f", "false", "n", "no", "off", "0"):
        return False
    return True
