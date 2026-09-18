"""Current in-memory profile model."""
from dataclasses import dataclass


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    profile_id: str
    display_name: str
    tags: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.profile_id, str) or not self.profile_id:
            raise SchemaError("invalid profile ID")
        if not isinstance(self.display_name, str) or not self.display_name:
            raise SchemaError("invalid display name")
        if not isinstance(self.tags, (list, tuple)) or any(
            not isinstance(tag, str) or not tag for tag in self.tags
        ):
            raise SchemaError("invalid tags")
        object.__setattr__(self, "tags", tuple(self.tags))
