from __future__ import annotations

import datetime
import inspect
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
                            "display_name": f"Example Agent {index}",
                            "member_since": "2026-08-27",
                            "profile_url": (
                                f"https://agentcommunity.org/m/example-agent-{index}"
                            ),
                        }
                        for index in range(5)
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

    assert CommunityStats.model_fields["member_count"].annotation is int
    assert CommunityStats.model_fields["note"].annotation is str

    lookup_schema = tools["lookup_member"]["outputSchema"]
    assert set(get_args(MemberLookup.model_fields["status"].annotation)) == set(
        lookup_schema["properties"]["status"]["enum"]
    )
    assert MemberLookup.model_fields["matches"].metadata[0].max_length == 5
    match_schema = lookup_schema["properties"]["matches"]["items"]
    assert set(MemberMatch.model_fields) == set(match_schema["properties"])
    assert set(MemberMatch.model_fields) == set(match_schema["required"])
    assert MemberMatch.model_fields["display_name"].annotation is str
    assert MemberMatch.model_fields["member_since"].annotation == datetime.date | None
    assert MemberMatch.model_fields["profile_url"].annotation is AnyUrl

    certificate_schema = tools["verify_certificate"]["outputSchema"]
    assert set(
        get_args(CertificateVerification.model_fields["status"].annotation)
    ) == set(certificate_schema["properties"]["status"]["enum"])
    assert CertificateVerification.model_fields["certificate_id"].annotation is str
    assert CertificateVerification.model_fields["valid_format"].annotation is bool
    for field_name in ("issued", "agent_name", "certificate_url"):
        assert type(None) in get_args(
            CertificateVerification.model_fields[field_name].annotation
        )
        assert "null" in certificate_schema["properties"][field_name]["type"]
    assert CertificateVerification.model_fields["certificate_url"].annotation == (
        AnyUrl | None
    )


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
