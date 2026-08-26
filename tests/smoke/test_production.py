from __future__ import annotations

import pytest

from agentcommunity import AgentCommunityClient


@pytest.mark.production
@pytest.mark.anyio
async def test_read_only_production_tools() -> None:
    async with AgentCommunityClient(timeout=8.0) as client:
        stats = await client.community_stats()
        certificate = await client.verify_certificate("invalid")

    assert stats.member_count >= 0
    assert certificate.status == "invalid_format"
    assert certificate.valid_format is False
    assert certificate.issued is False
