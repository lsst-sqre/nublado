from pydantic import BaseModel

from ..util import to_camel_case


class CamelCaseModel(BaseModel):
    """This is what we will use in place of BaseModel for all our Python
    Pydantic models.  Any configuration can be given in Helm-appropriate
    camelCase, but internal Python methods and objects will all be snake_case.
    """

    class Config:
        """Pydantic configuration."""

        alias_generator = to_camel_case
        allow_population_by_field_name = True
