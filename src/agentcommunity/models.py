from __future__ import annotations

import datetime
from typing import Any, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class CommunityStats(_StrictModel):
    member_count: int
    note: str


class MemberMatch(_StrictModel):
    display_name: str
    member_since: datetime.date | None
    profile_url: AnyUrl

    @field_validator("member_since", mode="before")
    @classmethod
    def parse_member_since(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.date.fromisoformat(value)
        return value


class MemberLookup(_StrictModel):
    status: Literal["member", "not_found", "ambiguous"]
    matches: tuple[MemberMatch, ...] = Field(max_length=5)

    @field_validator("matches", mode="before")
    @classmethod
    def freeze_matches(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(value)
        return value


class CertificateVerification(_StrictModel):
    certificate_id: str
    status: Literal["invalid_format", "not_found", "issued", "unavailable"]
    valid_format: bool
    issued: bool | None
    agent_name: str | None
    certificate_url: AnyUrl | None

    @model_validator(mode="after")
    def validate_certificate_state(self) -> CertificateVerification:
        expected = {
            "invalid_format": (False, False, False, False),
            "not_found": (True, False, False, False),
            "issued": (True, True, True, True),
            "unavailable": (True, None, False, False),
        }[self.status]
        actual = (
            self.valid_format,
            self.issued,
            self.agent_name is not None,
            self.certificate_url is not None,
        )
        if actual != expected:
            raise ValueError(
                f"certificate state is inconsistent with status {self.status!r}"
            )
        return self
