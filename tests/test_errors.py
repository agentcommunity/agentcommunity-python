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
        "__version__",
        "AgentCommunityClient",
        "CommunityStats",
        "MemberMatch",
        "MemberLookup",
        "CertificateVerification",
        "AgentCommunityError",
        "AgentCommunityTransportError",
        "AgentCommunityProtocolError",
        "AgentCommunityToolError",
    ]
    assert not hasattr(agentcommunity, "register_agent")
