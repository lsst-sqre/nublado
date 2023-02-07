"""General utility functions."""

import datetime
from typing import Any, Callable, Dict


def to_camel_case(string: str) -> str:
    """Convert a string to camel case.

    Originally written for use with Pydantic as an alias generator so that the
    model can be initialized from camel-case input (such as Kubernetes
    objects).

    Parameters
    ----------
    string
        Input string

    Returns
    -------
    str
        String converted to camel-case with the first character in lowercase.
    """
    components = string.split("_")
    return components[0] + "".join(c.title() for c in components[1:])


def validate_exactly_one_of(
    *settings: str,
) -> Callable[[Any, Dict[str, Any]], Any]:
    """Generate a validator imposing a one and only one constraint.

    Sometimes, models have a set of attributes of which one and only one may
    be set.  Ideally this is represented properly in the type system, but
    occasionally it's more convenient to use a validator.  This is a validator
    generator that can produce a validator function that ensures one and only
    one of an arbitrary set of attributes must be set.

    Parameters
    ----------
    *settings
        List of names of attributes, of which one and only one must be set.

    Returns
    -------
    Callable
        The validator.

    Examples
    --------
    Use this inside a Pydantic class as a validator as follows:

    .. code-block:: python

       class Foo(BaseModel):
           foo: Optional[str] = None
           bar: Optional[str] = None
           baz: Optional[str] = None

           _validate_options = validator("baz", always=True, allow_reuse=True)(
               validate_exactly_one_of("foo", "bar", "baz")
           )

    The attribute listed as the first argument to the ``validator`` call must
    be the last attribute in the model definition so that any other attributes
    have already been seen.
    """
    if len(settings) == 2:
        options = f"{settings[0]} and {settings[1]}"
    else:
        options = ", ".join(settings[:-1]) + ", and " + settings[-1]

    def validator(v: Any, values: Dict[str, Any]) -> Any:
        seen = v is not None
        for setting in settings:
            if setting in values and values[setting] is not None:
                if seen:
                    raise ValueError(f"only one of {options} may be given")
                seen = True
        if not seen:
            raise ValueError(f"one of {options} must be given")
        return v

    return validator


def now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


def stale(check_time: datetime.datetime, max_age: datetime.timedelta) -> bool:
    return now() - max_age > check_time


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
