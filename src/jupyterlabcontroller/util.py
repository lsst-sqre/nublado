"""General utility functions."""

import datetime
from typing import Any, Callable, Dict

from fastapi import HTTPException


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


def extract_bearer_token(header: str) -> str:
    """Verify that token starts with case-insensitive 'bearer ' and then
    return the part after that, which should be the token."""
    if header[:7].lower() != "bearer ":
        raise HTTPException(status_code=422, detail="Unprocessible Entity")
    return header[7:]


def now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)
