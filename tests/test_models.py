import datetime
import itertools
from typing import Any

import pytest
from pydantic import ValidationError

from agentcommunity import (
    CertificateVerification,
    CommunityStats,
    MemberLookup,
    MemberMatch,
)


def test_community_stats_accepts_exact_valid_data() -> None:
    stats = CommunityStats(member_count=29_700, note="Verified members")

    assert stats.member_count == 29_700
    assert stats.note == "Verified members"


@pytest.mark.parametrize("member_count", [True, "29700"])
def test_community_stats_rejects_integer_coercion(member_count: object) -> None:
    with pytest.raises(ValidationError):
        CommunityStats(member_count=member_count, note="Verified members")  # type: ignore[arg-type]


def test_community_stats_is_frozen_and_forbids_extras() -> None:
    stats = CommunityStats(member_count=29_700, note="Verified members")

    with pytest.raises(ValidationError):
        stats.member_count = 1
    with pytest.raises(ValidationError):
        CommunityStats(member_count=29_700, note="Verified members", extra=True)  # type: ignore[call-arg]


def test_member_match_parses_contract_date_and_absolute_url() -> None:
    match = MemberMatch.model_validate(
        {
            "display_name": "Example Agent",
            "member_since": "2026-08-27",
            "profile_url": "https://agentcommunity.org/m/example-agent",
        }
    )

    assert match.member_since == datetime.date(2026, 8, 27)
    assert str(match.profile_url) == "https://agentcommunity.org/m/example-agent"


def test_member_match_accepts_null_date() -> None:
    match = MemberMatch.model_validate(
        {
            "display_name": "Example Agent",
            "member_since": None,
            "profile_url": "https://agentcommunity.org/m/example-agent",
        }
    )

    assert match.member_since is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("member_since", "2026-02-30"),
        ("member_since", 20_260_827),
        ("profile_url", "/m/example-agent"),
        ("display_name", 123),
    ],
)
def test_member_match_rejects_invalid_or_coerced_fields(
    field: str, value: object
) -> None:
    data: dict[str, object] = {
        "display_name": "Example Agent",
        "member_since": "2026-08-27",
        "profile_url": "https://agentcommunity.org/m/example-agent",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        MemberMatch.model_validate(data)


def test_member_match_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        MemberMatch.model_validate(
            {
                "display_name": "Example Agent",
                "member_since": None,
                "profile_url": "https://agentcommunity.org/m/example-agent",
                "slug": "example-agent",
            }
        )


def make_match(index: int = 0) -> dict[str, object]:
    return {
        "display_name": f"Example Agent {index}",
        "member_since": "2026-08-27",
        "profile_url": f"https://agentcommunity.org/m/example-agent-{index}",
    }


@pytest.mark.parametrize("status", ["member", "not_found", "ambiguous"])
def test_member_lookup_accepts_exact_statuses_and_immutable_matches(
    status: str,
) -> None:
    lookup = MemberLookup.model_validate({"status": status, "matches": [make_match()]})

    assert isinstance(lookup.matches, tuple)
    assert isinstance(lookup.matches[0], MemberMatch)
    with pytest.raises(ValidationError):
        lookup.matches = ()


def test_member_lookup_rejects_sixth_match_invalid_status_and_extras() -> None:
    with pytest.raises(ValidationError):
        MemberLookup.model_validate(
            {"status": "ambiguous", "matches": [make_match(i) for i in range(6)]}
        )
    with pytest.raises(ValidationError):
        MemberLookup.model_validate({"status": "unknown", "matches": []})
    with pytest.raises(ValidationError):
        MemberLookup.model_validate(
            {"status": "member", "matches": [], "query": "Example"}
        )


def test_member_lookup_rejects_nested_extras() -> None:
    nested_match = make_match()
    nested_match["slug"] = "example-agent"

    with pytest.raises(ValidationError):
        MemberLookup.model_validate({"status": "member", "matches": [nested_match]})


VALID_CERTIFICATE_STATES: dict[
    str, tuple[bool, bool | None, str | None, str | None]
] = {
    "invalid_format": (False, False, None, None),
    "not_found": (True, False, None, None),
    "issued": (
        True,
        True,
        "Example Agent",
        "https://agentcommunity.org/certificates/AC-123",
    ),
    "unavailable": (True, None, None, None),
}


@pytest.mark.parametrize(
    ("status", "state"),
    VALID_CERTIFICATE_STATES.items(),
)
def test_certificate_verification_accepts_exact_valid_states(
    status: str,
    state: tuple[bool, bool | None, str | None, str | None],
) -> None:
    valid_format, issued, agent_name, certificate_url = state

    result = CertificateVerification.model_validate(
        {
            "certificate_id": "AC-123",
            "status": status,
            "valid_format": valid_format,
            "issued": issued,
            "agent_name": agent_name,
            "certificate_url": certificate_url,
        }
    )

    assert result.status == status
    assert result.valid_format is valid_format
    assert result.issued is issued
    assert result.agent_name == agent_name
    if certificate_url is None:
        assert result.certificate_url is None
    else:
        assert str(result.certificate_url) == certificate_url


INVALID_CERTIFICATE_STATES = [
    pytest.param(status, state, id=f"{status}-{state!r}")
    for status, expected in VALID_CERTIFICATE_STATES.items()
    for state in itertools.product(
        (False, True),
        (False, True, None),
        (None, "Example Agent"),
        (None, "https://agentcommunity.org/certificates/AC-123"),
    )
    if state != expected
]


@pytest.mark.parametrize(("status", "state"), INVALID_CERTIFICATE_STATES)
def test_certificate_verification_rejects_every_inconsistent_state(
    status: str,
    state: tuple[bool, bool | None, str | None, str | None],
) -> None:
    valid_format, issued, agent_name, certificate_url = state

    with pytest.raises(ValidationError, match="certificate state is inconsistent"):
        CertificateVerification.model_validate(
            {
                "certificate_id": "AC-123",
                "status": status,
                "valid_format": valid_format,
                "issued": issued,
                "agent_name": agent_name,
                "certificate_url": certificate_url,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("certificate_id", 123),
        ("status", "unknown"),
        ("valid_format", 1),
        ("issued", 0),
        ("agent_name", 123),
        ("certificate_url", "/certificates/AC-123"),
    ],
)
def test_certificate_verification_rejects_invalid_or_coerced_fields(
    field: str, value: Any
) -> None:
    data: dict[str, Any] = {
        "certificate_id": "AC-123",
        "status": "issued",
        "valid_format": True,
        "issued": True,
        "agent_name": "Example Agent",
        "certificate_url": "https://agentcommunity.org/certificates/AC-123",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        CertificateVerification.model_validate(data)


def test_certificate_verification_is_frozen_and_forbids_extras() -> None:
    result = CertificateVerification.model_validate(
        {
            "certificate_id": "AC-123",
            "status": "not_found",
            "valid_format": True,
            "issued": False,
            "agent_name": None,
            "certificate_url": None,
        }
    )

    with pytest.raises(ValidationError):
        result.issued = True
    with pytest.raises(ValidationError):
        CertificateVerification.model_validate(
            {
                "certificate_id": "AC-123",
                "status": "not_found",
                "valid_format": True,
                "issued": False,
                "agent_name": None,
                "certificate_url": None,
                "detail": "missing",
            }
        )
