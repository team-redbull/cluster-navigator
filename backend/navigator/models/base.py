from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    """Base for everything that crosses the wire.

    Python uses snake_case, JSON uses camelCase. Unknown fields are ignored so
    a newer collector can talk to an older server and the other way around.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )
