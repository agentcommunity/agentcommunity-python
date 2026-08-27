class AgentCommunityError(Exception):
    """Base exception for Agent Community SDK errors."""


class AgentCommunityTransportError(AgentCommunityError):
    """Raised when communication with the Agent Community endpoint fails."""


class AgentCommunityProtocolError(AgentCommunityError):
    """Raised when an MCP response violates the expected protocol."""


class AgentCommunityToolError(AgentCommunityError):
    """Raised when an Agent Community MCP tool reports an error."""
