import hashlib
from typing import Any

EXPECTED_CONTRACT_SHA256 = (
    "53c6c703f1dcf2bb28a9d31287f001d9644d64900ed39edf027f77bf01640e87"
)


def test_contract_fixture_has_approved_digest(contract_bytes: bytes) -> None:
    assert hashlib.sha256(contract_bytes).hexdigest() == EXPECTED_CONTRACT_SHA256


def test_contract_fixture_pins_advertised_revision(
    contract: dict[str, Any],
) -> None:
    assert contract["advertised_revision"] == "2026-07-28"


def test_get_community_stats_schema_is_pinned(contract: dict[str, Any]) -> None:
    tools = {tool["name"]: tool for tool in contract["product_tools"]}
    tool = tools["get_community_stats"]

    assert tool["inputSchema"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert tool["outputSchema"] == {
        "type": "object",
        "properties": {
            "member_count": {"type": "integer"},
            "note": {"type": "string"},
        },
        "required": ["member_count", "note"],
        "additionalProperties": False,
    }


def test_lookup_member_schema_is_pinned(contract: dict[str, Any]) -> None:
    tools = {tool["name"]: tool for tool in contract["product_tools"]}
    tool = tools["lookup_member"]

    assert tool["inputSchema"] == {
        "type": "object",
        "properties": {
            "query": {
                "description": "Exact display name or slug; not free-text search.",
                "maxLength": 200,
                "minLength": 1,
                "type": "string",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    assert tool["outputSchema"] == {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["member", "not_found", "ambiguous"]},
            "matches": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "display_name": {"type": "string"},
                        "member_since": {
                            "format": "date",
                            "type": ["string", "null"],
                        },
                        "profile_url": {"type": "string", "format": "uri"},
                    },
                    "required": ["display_name", "member_since", "profile_url"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["status", "matches"],
        "additionalProperties": False,
    }


def test_verify_certificate_schema_is_pinned(contract: dict[str, Any]) -> None:
    tools = {tool["name"]: tool for tool in contract["product_tools"]}
    tool = tools["verify_certificate"]

    assert tool["inputSchema"] == {
        "type": "object",
        "properties": {
            "certificate_id": {
                "description": "Certificate ID, e.g. MESA-DD6-660J.",
                "type": "string",
            }
        },
        "required": ["certificate_id"],
        "additionalProperties": False,
    }
    assert tool["outputSchema"] == {
        "type": "object",
        "properties": {
            "certificate_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["invalid_format", "not_found", "issued", "unavailable"],
            },
            "valid_format": {"type": "boolean"},
            "issued": {"type": ["boolean", "null"]},
            "agent_name": {"type": ["string", "null"]},
            "certificate_url": {
                "format": "uri",
                "type": ["string", "null"],
            },
        },
        "required": [
            "certificate_id",
            "status",
            "valid_format",
            "issued",
            "agent_name",
            "certificate_url",
        ],
        "additionalProperties": False,
    }


def test_registration_is_not_exported(contract: dict[str, Any]) -> None:
    import agentcommunity

    tool_names = {tool["name"] for tool in contract["product_tools"]}
    assert "register_agent" in tool_names
    assert "register_agent" not in getattr(agentcommunity, "__all__", ())
    assert not hasattr(agentcommunity, "register_agent")
