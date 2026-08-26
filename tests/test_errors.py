import agentcommunity


def test_public_exception_hierarchy() -> None:
    assert issubclass(
        agentcommunity.AgentCommunityTransportError,
        agentcommunity.AgentCommunityError,
    )
    assert issubclass(
        agentcommunity.AgentCommunityProtocolError,
        agentcommunity.AgentCommunityError,
    )
    assert issubclass(
        agentcommunity.AgentCommunityToolError,
        agentcommunity.AgentCommunityError,
    )


def test_public_exports_are_exact() -> None:
    assert agentcommunity.__all__ == [
        "AgentCommunityError",
        "AgentCommunityProtocolError",
        "AgentCommunityToolError",
        "AgentCommunityTransportError",
        "CertificateVerification",
        "CommunityStats",
        "MemberLookup",
        "MemberMatch",
        "__version__",
    ]
    assert not hasattr(agentcommunity, "register_agent")
