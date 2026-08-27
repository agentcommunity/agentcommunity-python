from __future__ import annotations

import datetime
import inspect
from copy import deepcopy
from typing import Any, get_args

import pytest
from fakes import FakeMCPClient, RecordingClientFactory, successful_result
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from pydantic import AnyUrl, BaseModel

from agentcommunity import (
    AgentCommunityClient,
    CertificateVerification,
    CommunityStats,
    MemberLookup,
    MemberMatch,
)

WRAPPED_TOOLS = {
    "community_stats": "get_community_stats",
    "lookup_member": "lookup_member",
    "verify_certificate": "verify_certificate",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def product_tools(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in contract["product_tools"]}


def assert_schema_type_and_format(
    schema: dict[str, Any],
    expected_types: set[str],
    expected_format: str | None = None,
) -> None:
    raw_type = schema.get("type")
    actual_types = {raw_type} if isinstance(raw_type, str) else set(raw_type or [])
    assert actual_types == expected_types
    assert schema.get("format") == expected_format


def assert_public_scalar_compatibility(
    tools: dict[str, dict[str, Any]],
) -> None:
    stats = tools["get_community_stats"]["outputSchema"]["properties"]
    assert CommunityStats.model_fields["member_count"].annotation is int
    assert_schema_type_and_format(stats["member_count"], {"integer"})
    assert CommunityStats.model_fields["note"].annotation is str
    assert_schema_type_and_format(stats["note"], {"string"})

    matches = tools["lookup_member"]["outputSchema"]["properties"]["matches"]
    match = matches["items"]["properties"]
    assert MemberMatch.model_fields["display_name"].annotation is str
    assert_schema_type_and_format(match["display_name"], {"string"})
    assert MemberMatch.model_fields["member_since"].annotation == datetime.date | None
    assert_schema_type_and_format(match["member_since"], {"string", "null"}, "date")
    assert MemberMatch.model_fields["profile_url"].annotation is AnyUrl
    assert_schema_type_and_format(match["profile_url"], {"string"}, "uri")

    certificate = tools["verify_certificate"]["outputSchema"]["properties"]
    assert CertificateVerification.model_fields["certificate_id"].annotation is str
    assert_schema_type_and_format(certificate["certificate_id"], {"string"})
    assert CertificateVerification.model_fields["valid_format"].annotation is bool
    assert_schema_type_and_format(certificate["valid_format"], {"boolean"})
    assert CertificateVerification.model_fields["issued"].annotation == bool | None
    assert_schema_type_and_format(certificate["issued"], {"boolean", "null"})
    assert CertificateVerification.model_fields["agent_name"].annotation == str | None
    assert_schema_type_and_format(certificate["agent_name"], {"string", "null"})
    assert CertificateVerification.model_fields["certificate_url"].annotation == (
        AnyUrl | None
    )
    assert_schema_type_and_format(
        certificate["certificate_url"], {"string", "null"}, "uri"
    )


@pytest.mark.anyio
async def test_emitted_arguments_satisfy_pinned_input_schemas(
    contract: dict[str, Any],
) -> None:
    fake = FakeMCPClient()
    fake.results = [
        successful_result({"member_count": 1, "note": "fixture"}),
        successful_result({"status": "not_found", "matches": []}),
        successful_result(
            {
                "certificate_id": " malformed ",
                "status": "invalid_format",
                "valid_format": False,
                "issued": False,
                "agent_name": None,
                "certificate_url": None,
            }
        ),
    ]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        await client.community_stats()
        await client.lookup_member(" member ")
        await client.verify_certificate(" malformed ")

    tools = product_tools(contract)
    for tool_name, arguments in fake.calls:
        Draft202012Validator(tools[tool_name]["inputSchema"]).validate(arguments)

    assert fake.calls == [
        ("get_community_stats", {}),
        ("lookup_member", {"query": "member"}),
        ("verify_certificate", {"certificate_id": " malformed "}),
    ]


@pytest.mark.anyio
async def test_lookup_validation_tracks_pinned_input_boundaries(
    contract: dict[str, Any],
) -> None:
    query_schema = product_tools(contract)["lookup_member"]["inputSchema"][
        "properties"
    ]["query"]
    minimum = query_schema["minLength"]
    maximum = query_schema["maxLength"]
    accepted_queries = ["q" * minimum, "q" * maximum]
    rejected_queries = ["q" * (minimum - 1), "q" * (maximum + 1)]
    fake = FakeMCPClient()
    fake.results = [
        successful_result({"status": "not_found", "matches": []})
        for _ in accepted_queries
    ]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        for query in accepted_queries:
            await client.lookup_member(f" {query} ")
        for query in rejected_queries:
            with pytest.raises(ValueError):
                await client.lookup_member(query)

    assert fake.calls == [
        ("lookup_member", {"query": query}) for query in accepted_queries
    ]


@pytest.mark.parametrize(
    ("tool_name", "model_type", "examples"),
    [
        (
            "get_community_stats",
            CommunityStats,
            [{"member_count": 29_700, "note": "Verified members"}],
        ),
        (
            "lookup_member",
            MemberLookup,
            [
                {"status": "not_found", "matches": []},
                {
                    "status": "member",
                    "matches": [
                        {
                            "display_name": "Example Agent",
                            "member_since": None,
                            "profile_url": "https://agentcommunity.org/m/example-agent",
                        }
                    ],
                },
                {
                    "status": "ambiguous",
                    "matches": [
                        {
                            "display_name": "Example Agent 2",
                            "member_since": "2026-08-27",
                            "profile_url": "https://agentcommunity.org/m/example-agent-2",
                        }
                    ],
                },
            ],
        ),
        (
            "verify_certificate",
            CertificateVerification,
            [
                {
                    "certificate_id": "bad",
                    "status": "invalid_format",
                    "valid_format": False,
                    "issued": False,
                    "agent_name": None,
                    "certificate_url": None,
                },
                {
                    "certificate_id": "MESA-DD6-660J",
                    "status": "not_found",
                    "valid_format": True,
                    "issued": False,
                    "agent_name": None,
                    "certificate_url": None,
                },
                {
                    "certificate_id": "MESA-DD6-660J",
                    "status": "issued",
                    "valid_format": True,
                    "issued": True,
                    "agent_name": "Example Agent",
                    "certificate_url": (
                        "https://agentcommunity.org/certificates/MESA-DD6-660J"
                    ),
                },
                {
                    "certificate_id": "MESA-DD6-660J",
                    "status": "unavailable",
                    "valid_format": True,
                    "issued": None,
                    "agent_name": None,
                    "certificate_url": None,
                },
            ],
        ),
    ],
)
def test_fixture_valid_outputs_map_directly_to_public_models(
    contract: dict[str, Any],
    tool_name: str,
    model_type: type[BaseModel],
    examples: list[dict[str, object]],
) -> None:
    schema = product_tools(contract)[tool_name]["outputSchema"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    for example in examples:
        validator.validate(example)
        result = model_type.model_validate(example)
        assert set(result.model_dump(mode="json")) == set(schema["required"])


def test_public_model_shapes_align_with_pinned_output_contract(
    contract: dict[str, Any],
) -> None:
    tools = product_tools(contract)
    models: dict[str, type[BaseModel]] = {
        "get_community_stats": CommunityStats,
        "lookup_member": MemberLookup,
        "verify_certificate": CertificateVerification,
    }

    for tool_name, model_type in models.items():
        output_schema = tools[tool_name]["outputSchema"]
        assert set(model_type.model_fields) == set(output_schema["properties"])
        assert {
            name
            for name, field in model_type.model_fields.items()
            if field.is_required()
        } == set(output_schema["required"])

    assert_public_scalar_compatibility(tools)

    lookup_schema = tools["lookup_member"]["outputSchema"]
    assert set(get_args(MemberLookup.model_fields["status"].annotation)) == set(
        lookup_schema["properties"]["status"]["enum"]
    )
    model_matches_schema = MemberLookup.model_json_schema()["properties"]["matches"]
    assert (
        model_matches_schema["maxItems"]
        == lookup_schema["properties"]["matches"]["maxItems"]
    )
    match_schema = lookup_schema["properties"]["matches"]["items"]
    assert set(MemberMatch.model_fields) == set(match_schema["properties"])
    assert set(MemberMatch.model_fields) == set(match_schema["required"])

    certificate_schema = tools["verify_certificate"]["outputSchema"]
    assert set(
        get_args(CertificateVerification.model_fields["status"].annotation)
    ) == set(certificate_schema["properties"]["status"]["enum"])
    for field_name in ("issued", "agent_name", "certificate_url"):
        assert type(None) in get_args(
            CertificateVerification.model_fields[field_name].annotation
        )
        assert "null" in certificate_schema["properties"][field_name]["type"]


@pytest.mark.parametrize(
    ("tool_name", "nested_matches", "field_name", "mutated_schema"),
    [
        ("get_community_stats", False, "member_count", {"type": "number"}),
        (
            "verify_certificate",
            False,
            "issued",
            {"type": ["boolean", "integer", "null"]},
        ),
        (
            "lookup_member",
            True,
            "member_since",
            {"type": ["string", "null"]},
        ),
    ],
)
def test_scalar_compatibility_rejects_incompatible_contract_mutations(
    contract: dict[str, Any],
    tool_name: str,
    nested_matches: bool,
    field_name: str,
    mutated_schema: dict[str, Any],
) -> None:
    tools = product_tools(deepcopy(contract))
    properties = tools[tool_name]["outputSchema"]["properties"]
    if nested_matches:
        properties = properties["matches"]["items"]["properties"]
    properties[field_name] = mutated_schema

    with pytest.raises(AssertionError):
        assert_public_scalar_compatibility(tools)


def test_only_approved_contract_tools_have_public_wrappers(
    contract: dict[str, Any],
) -> None:
    contract_names = set(product_tools(contract))
    public_async_methods = {
        name
        for name, value in inspect.getmembers(
            AgentCommunityClient, predicate=inspect.iscoroutinefunction
        )
        if not name.startswith("_") and name != "close"
    }

    assert set(WRAPPED_TOOLS.values()) <= contract_names
    assert "register_agent" in contract_names
    assert public_async_methods == set(WRAPPED_TOOLS)
    assert not hasattr(AgentCommunityClient, "register_agent")
