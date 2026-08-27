# Agent Community Python SDK Design

**Date:** 2026-08-27  
**Status:** Approved for implementation

## Objective

Create a small, official Python SDK for the public Agent Community MCP endpoint. The package should give Python agents a typed, dependable way to use the three read-only public capabilities without making callers handle MCP protocol details.

The SDK is also intended to give package registries and agent-readiness scanners an unambiguous official Python package associated with `agentcommunity.org`. Publication and later advertisement on the website are separate release gates; this repository must be useful independently of scanner behavior.

## Repository and package identity

- Standalone repository: `agentcommunity/agentcommunity-python`.
- PyPI distribution: `agentcommunity`.
- Python import: `agentcommunity`.
- Initial version: `0.1.0`.
- Supported Python: 3.10 and newer.
- License: MIT.
- Package homepage and project URLs must point to `https://agentcommunity.org` and the official source repository.
- Runtime dependencies:
  - `jsonschema>=4.20,<5`
  - `mcp>=2.1.1,<3`
  - `pydantic>=2.12,<3`

`jsonschema` is a direct runtime dependency because protocol-error classification imports `jsonschema.exceptions.ValidationError`. The SDK must declare that import rather than rely on MCP's transitive dependency.

The PyPI name must be checked again immediately before publication. A currently unclaimed name is not a reservation.

## Public API

The package exports one asynchronous client:

```python
from agentcommunity import AgentCommunityClient

async with AgentCommunityClient() as client:
    stats = await client.community_stats()
    members = await client.lookup_member("example")
    certificate = await client.verify_certificate("AC-...")
```

`AgentCommunityClient` has these constructor settings:

- `endpoint`: defaults to `https://agentcommunity.org/mcp`.
- `timeout`: defaults to 15 seconds and applies to connection and tool operations.

It exposes exactly these public capability methods in version 0.1:

- `community_stats() -> CommunityStats`
- `lookup_member(query: str) -> MemberLookup`
- `verify_certificate(certificate_id: str) -> CertificateVerification`

The client is an async context manager. One connected instance supports multiple sequential calls. Calls made before entering or after leaving the context fail with a package protocol error. Closing is idempotent before entry and after a completed teardown attempt. The SDK does not expose its underlying MCP client or session.

Version 0.1 intentionally omits:

- `register_agent`, because registration requires explicit current-turn authorization and is not a safe convenience method.
- A synchronous facade.
- A command-line interface.
- A stdio connector or proxy.
- Authentication configuration.
- Automatic retries.
- One-shot helper functions.
- Raw MCP protocol/version controls.

The server may advertise additional tools. The SDK must ignore unknown tools and continue to operate with the three supported methods.

## Transport and lifecycle

The implementation wraps the official MCP Python SDK high-level client, created as `mcp.Client(endpoint)`. It must use the public SDK interface rather than duplicating Streamable HTTP or JSON-RPC behavior.

The configured timeout covers connection/handshake and each tool call. The connection deadline lexically encloses the official client lifecycle so AnyIO cancel scopes remain correctly nested, and it is disabled after connection succeeds. Tool calls use the official client's per-call `read_timeout_seconds` option. Official teardown is deliberately not wrapped in another timeout: it runs once because cancellation can consume cleanup callbacks that cannot safely be retried. A failed or cancelled teardown leaves that SDK instance terminal and non-callable; later `close()` calls are safe no-ops.

For each typed method, the wrapper:

1. Requires an active client context.
2. Invokes the exact MCP tool name with a validated argument object.
3. Enforces the configured timeout without suppressing caller cancellation.
4. Checks `is_error` before inspecting payload data.
5. Requires `structured_content`.
6. Validates the structured result with the corresponding strict Pydantic model.
7. Returns that immutable model.

The wrapper never parses human-readable text as a fallback. Missing or malformed structured data is a protocol error even if text content looks usable.

There is no automatic retry in version 0.1. Retrying might repeat a request after an ambiguous network failure, and the thin client should leave policy to the caller. Native task cancellation must propagate unchanged.

## Input validation

`lookup_member` trims surrounding whitespace. The trimmed query must contain between 1 and 200 characters inclusive. Invalid values fail locally before transport with a normal Python `ValueError`.

`verify_certificate` passes the supplied string to the server rather than imposing a local format validator. The server's `invalid_format` response is a documented, typed outcome. Basic Python type enforcement remains in place.

## Result models

All exported result models are frozen Pydantic models with strict validation and `extra="forbid"`. They are data contracts, not mutable response dictionaries.

### `CommunityStats`

Represents the complete structured result of `get_community_stats`:

- `member_count: int`
- `note: str`

### `MemberMatch`

Represents one member match from `lookup_member`:

- `display_name: str`
- `member_since: datetime.date | None`
- `profile_url: pydantic.AnyUrl`

### `MemberLookup`

Represents the complete lookup response:

- `status: Literal["member", "not_found", "ambiguous"]`
- `matches: tuple[MemberMatch, ...]`, limited to at most five items

### `CertificateVerification`

Represents all four public certificate outcomes with these fields:

- `certificate_id: str`
- `status: Literal["invalid_format", "not_found", "issued", "unavailable"]`
- `valid_format: bool`
- `issued: bool | None`
- `agent_name: str | None`
- `certificate_url: pydantic.AnyUrl | None`

Model validation enforces these cross-field invariants:

| Status | `valid_format` | `issued` | Agent and URL fields |
|---|---:|---:|---|
| `invalid_format` | `false` | `false` | absent |
| `not_found` | `true` | `false` | absent |
| `issued` | `true` | `true` | present |
| `unavailable` | `true` | `null` | absent |

The field names and URL/date representations come from the pinned MCP contract, not an inferred example response.

## Error model

The package exports:

- `AgentCommunityError`: common package base exception.
- `AgentCommunityTransportError`: connection, timeout, and transport failures.
- `AgentCommunityProtocolError`: lifecycle misuse, missing structured content, and schema/protocol mismatch.
- `AgentCommunityToolError`: an MCP tool result marked as an error.

Translated errors preserve the upstream exception through `__cause__`. Caller cancellation is not translated. Local lookup validation uses `ValueError`, keeping ordinary argument mistakes distinct from remote failures.

Tool errors should retain safe diagnostic text supplied by MCP without exposing internal transport objects. Timeout errors identify the operation and configured duration.

## Contract fixture and compatibility boundary

Tests vendor the immutable production contract bundle file:

`tests/contracts/1.5.0/mcp.json`

The checked-in fixture must match SHA-256:

`53c6c703f1dcf2bb28a9d31287f001d9644d64900ed39edf027f77bf01640e87`

The bundle manifest currently identifies release `1.5.0` and manifest digest:

`6a9234c031ea66935fb14456ddb5859708af7e46a9ebe2595c4b12aaaf26a1ed`

Tests verify the fixture digest before relying on its schema. They must not fetch or follow `latest.json`, because mutable production state would make pull-request tests nondeterministic. Updating the fixture is an explicit compatibility change requiring review.

The runtime client relies on normal MCP discovery and remains compatible when the endpoint adds unrelated tools. Only incompatible changes to the three wrapped tool contracts require an SDK release.

## Testing strategy

Implementation follows test-driven development: each behavior begins with a failing test, then the minimum implementation, followed by refactoring while green.

### Offline unit tests

Unit tests cover:

- All four certificate states and every cross-field invalid combination.
- Exact result-model parsing and rejection of extra or incorrectly typed fields.
- Member query trimming plus 1- and 200-character boundaries.
- Client lifecycle, repeated sequential calls, and idempotent close.
- Endpoint and timeout overrides.
- Tool-error, missing-structured-content, malformed-schema, transport, and timeout translation.
- Preservation of exception causes.
- Cancellation propagation.
- Certificate IDs passed through for server-side format handling.
- Tolerance of additional advertised tools.

### MCP integration test

Offline integration tests use the official MCP client stack against deterministic in-process servers. Task 3 exercises the lifecycle/timeout and advertised output-schema boundaries early because mocks cannot model the official stack's persistent AnyIO cancel scopes. Task 4 retains end-to-end coverage of all three public methods and structured-content decoding without reaching production.

### Contract tests

Contract tests verify the immutable fixture digest and assert that the three supported tool input/output schemas remain compatible with the public models and call shapes.

### Production smoke test

A scheduled and manually dispatched workflow may call the production endpoint. It is never required for a pull request, never invokes registration, and limits itself to read-only calls. Its purpose is operational drift detection, not deterministic unit verification.

### Supported matrix and artifact checks

Continuous integration runs:

- Python 3.10 and the latest supported stable Python.
- Lowest allowed and newest allowed dependency resolution.
- Ruff formatting and linting.
- Static type checking.
- Pytest.
- Wheel and source-distribution build.
- `twine check`.
- Import and minimal usage checks from a clean wheel environment.
- Installation and tests from the source distribution.
- A checked README example smoke test.

Artifact verification receives a separately prepared wheelhouse and performs
all clean installs with `--no-index`. Registry resolution belongs only to the
wheelhouse-preparation step; verification fails closed when that input is
missing or incomplete.

End-to-end tests should avoid dependence on developer credentials or mutable registry state.

## Documentation

The README includes:

- What the package wraps and the official endpoint.
- Installation instructions.
- A complete async example.
- Method and model reference.
- Error-handling example.
- Explicit statement that registration is deliberately not wrapped.
- Supported Python and dependency policy.
- Links to Agent Community MCP documentation and security reporting.

`SECURITY.md` provides a responsible disclosure route and supported-version policy. Changelog and contribution guidance should remain concise for the initial release.

## Release design

Releases use PyPI Trusted Publishing with provenance; no long-lived PyPI token is stored. The release workflow:

1. Builds wheel and source distribution once from a tagged commit.
2. Tests those exact artifacts in clean environments.
3. Publishes the unchanged artifacts after the configured trusted-publisher gate.

Before building, the release workflow requires the Git tag to equal `v` plus
the exact `project.version` from `pyproject.toml`.

Creating the remote repository, pushing commits, configuring PyPI, and publishing are external state changes and require explicit user authorization. Local implementation can be completed and committed before those gates.

After the package is publicly installed and verified, a separate Agent Community website change may add it to the official package registry and discovery outputs. The website must not advertise an unpublished package. The website change is outside this repository's version 0.1 implementation scope.

## Acceptance criteria

Version 0.1 is ready for publication when:

- The distribution builds reproducibly as wheel and source distribution.
- A clean environment can install each artifact and import the documented public API.
- All unit, integration, contract, lint, format, and type checks pass on the supported matrix.
- The README example executes against the deterministic test transport.
- The public API contains only the approved client, methods, models, and errors.
- The pinned MCP contract fixture has the approved digest.
- Release metadata points to the official domain and source repository.
- No secrets, publication credentials, registration calls, or website advertisement are included.
