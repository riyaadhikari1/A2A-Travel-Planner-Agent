from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactType(StrEnum):
    WEATHER         = "weather"
    DOMESTIC_FLIGHT = "domestic_flight"
    INTL_FLIGHT     = "intl_flight"
    HOTEL           = "hotel"
    BUDGET          = "budget"


from pydantic import BaseModel, Field, field_validator

class Artifact(BaseModel):
    artifact_type: ArtifactType | str
    agent_name:    str
    payload:       dict[str, Any]
    created_at:    datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("artifact_type", mode="before")
    @classmethod
    def coerce_artifact_type(cls, v: Any) -> ArtifactType | str:
        if isinstance(v, ArtifactType):
            return v
        try:
            return ArtifactType(v)
        except ValueError:
            return v