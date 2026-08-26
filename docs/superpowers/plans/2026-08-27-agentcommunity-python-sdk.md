# Agent Community Python SDK Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan task by task. Every implementation task follows `superpowers:test-driven-development`, then receives spec-compliance and code-quality reviews before the next task.

**Goal:** Build and release-prepare a small, typed, asynchronous Python SDK for the three read-only tools at `https://agentcommunity.org/mcp`.

**Architecture:** `AgentCommunityClient` is an async context-manager wrapper around the official high-level `mcp.Client`. A private transport adapter owns MCP lifecycle and exception translation; public methods validate arguments and turn required `structured_content` into strict, frozen Pydantic models. Tests pin the immutable 1.5.0 MCP contract and exercise the real MCP client stack locally, while production smoke checks stay optional and read-only.

**Tech Stack:** Python 3.10+, MCP Python SDK 2.x, Pydantic 2.x, Hatchling, pytest/AnyIO, Ruff, mypy, GitHub Actions, PyPI Trusted Publishing.

**Design reference:** `docs/superpowers/specs/2026-08-27-agentcommunity-python-sdk-design.md`

---

## Task 1: Scaffold packaging and pin the immutable MCP contract

**Files:**

- Create: `pyproject.toml`
- Create: `src/agentcommunity/__init__.py`
- Create: `src/agentcommunity/py.typed`
- Create: `tests/contracts/1.5.0/mcp.json`
- Create: `tests/test_contract_fixture.py`
- Create: `tests/conftest.py`

### Step 1: Write the failing fixture tests

Create `tests/test_contract_fixture.py` with tests that:

- Read `tests/contracts/1.5.0/mcp.json` as bytes and assert SHA-256 `53c6c703f1dcf2bb28a9d31287f001d9644d64900ed39edf027f77bf01640e87`.
- Parse JSON and assert `advertised_revision == "2026-07-28"`.
- Index `product_tools` by name and assert the three supported tools exist with their exact input/output schemas relevant to this SDK:
  - `get_community_stats`: empty object input; required `member_count`, `note`.
  - `lookup_member`: required `query`, length 1..200; output status enum, maximum five matches, required match fields.
  - `verify_certificate`: required `certificate_id`; exact four-value status enum and required output fields.
- Assert `register_agent` exists in the fixture but is deliberately absent from the package export surface.

Do not fetch production in a test.

### Step 2: Run the test to verify it fails

Run: `python -m pytest tests/test_contract_fixture.py -q`

Expected: FAIL because package/test dependencies and the fixture do not exist yet.

### Step 3: Add package metadata and the exact fixture

Create a PEP 621 `pyproject.toml` using Hatchling with:

- Distribution `agentcommunity`, version `0.1.0`, Python `>=3.10`, MIT metadata.
- Homepage `https://agentcommunity.org`, documentation `https://agentcommunity.org/mcp/docs`, source `https://github.com/agentcommunity/agentcommunity-python`, issues URL, and typed-package classifier.
- Dependencies exactly bounded as `mcp>=2.1.1,<3` and `pydantic>=2.12,<3`.
- Dev dependency groups sufficient for pytest, AnyIO, Ruff, mypy, build, and Twine.
- Ruff target Python 3.10 and a focused rule set; mypy strict mode for `src` and `tests`; pytest test path/configuration.
- Hatch wheel package path `src/agentcommunity` and include `py.typed`.

Create a minimal `src/agentcommunity/__init__.py` exposing only `__version__ = "0.1.0"` for now. Add the empty `py.typed` marker.

Copy the already verified immutable bytes from:

`https://agentcommunity.org/.well-known/agentcommunity-contracts/1.5.0/mcp.json`

into `tests/contracts/1.5.0/mcp.json`. Immediately verify its local SHA-256. The file is test evidence and must not be reformatted.

Use `tests/conftest.py` only for focused reusable fixture loading; do not create global magic or network fixtures.

### Step 4: Install and run focused checks

Create a local virtual environment and install the package with development dependencies using the project metadata. Run:

```bash
python -m pytest tests/test_contract_fixture.py -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests
python -m build
python -m twine check dist/*
```

Expected: all pass. Remove generated `dist/` after verifying it is ignored.

### Step 5: Commit

```bash
git add pyproject.toml src/agentcommunity tests
git commit -m "build: scaffold Python SDK package"
```

## Task 2: Implement strict public models and exception types

**Files:**

- Create: `src/agentcommunity/errors.py`
- Create: `src/agentcommunity/models.py`
- Modify: `src/agentcommunity/__init__.py`
- Create: `tests/test_errors.py`
- Create: `tests/test_models.py`

### Step 1: Write failing model and exception tests

Test the exact public hierarchy and model behavior:

- Four exception classes exist and inherit as specified in the design.
- `CommunityStats(member_count=..., note=...)` accepts exact valid data; rejects bool-as-int, string-as-int, mutation, and extra keys.
- `MemberMatch` parses an ISO date into `datetime.date`, accepts `None`, parses a valid absolute profile URL, and rejects invalid dates/URLs/extras.
- `MemberLookup` supports statuses `member`, `not_found`, `ambiguous`, stores matches immutably, rejects a sixth match, invalid status, list mutation, and extras.
- `CertificateVerification` accepts each of the four valid state combinations and rejects every inconsistent combination of status, `valid_format`, `issued`, and nullable agent/URL fields.
- Strict validation rejects coercion and unknown fields throughout nested models.
- `agentcommunity.__all__` exposes only the approved version, four result models, client placeholder only once it exists, and four exceptions; it never exports `register_agent` or internals.

Use table-driven tests for certificate states and invalid cross-field cases.

### Step 2: Run tests to verify failure

Run: `python -m pytest tests/test_models.py tests/test_errors.py -q`

Expected: FAIL with missing modules/types.

### Step 3: Implement the minimum public data layer

In `errors.py`, define:

- `AgentCommunityError`
- `AgentCommunityTransportError`
- `AgentCommunityProtocolError`
- `AgentCommunityToolError`

All specific errors inherit from `AgentCommunityError`. Keep constructors ordinary unless later transport code needs safe structured context.

In `models.py`:

- Use a shared private strict/frozen/extra-forbid Pydantic base model.
- Implement the exact fields from the design.
- Use `datetime.date`, `pydantic.AnyUrl`, `Literal`, and immutable tuples.
- Apply a maximum length of five to `MemberLookup.matches`.
- Use an after-model validator for certificate state invariants with a clear error message.

Update package exports. Do not add client behavior, helper factories, serialization wrappers, or extra models.

### Step 4: Verify and refactor

Run:

```bash
python -m pytest tests/test_models.py tests/test_errors.py tests/test_contract_fixture.py -q
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src tests
```

Expected: all pass.

### Step 5: Commit

```bash
git add src/agentcommunity tests/test_models.py tests/test_errors.py
git commit -m "feat: add strict SDK result models"
```

## Task 3: Implement client lifecycle and error translation

**Files:**

- Create: `src/agentcommunity/_transport.py`
- Create: `src/agentcommunity/client.py`
- Modify: `src/agentcommunity/__init__.py`
- Create: `tests/fakes.py`
- Create: `tests/test_client_lifecycle.py`
- Create: `tests/test_client_errors.py`

### Step 1: Write failing lifecycle tests

Use a small injected factory/fake at the private transport seam. Test:

- Default endpoint is `https://agentcommunity.org/mcp` and default timeout is 15 seconds.
- Endpoint and positive finite timeout can be overridden; invalid timeout or endpoint types/values fail locally.
- `async with AgentCommunityClient()` opens one underlying `mcp.Client` and closes it once.
- A connected client supports multiple sequential calls without reconnecting.
- Calls before enter and after exit raise `AgentCommunityProtocolError`.
- Re-entering an active instance fails predictably.
- `close()` is safe and idempotent, including after context exit.
- Cancellation during connect or call propagates as `asyncio.CancelledError` (or the active cancellation class), not a package error.

Keep the injection mechanism private. Tests may import a private constructor/factory seam directly, but it must not appear in `agentcommunity.__all__` or user documentation.

### Step 2: Write failing error-translation tests

Test:

- Connection and generic MCP/HTTP failures become `AgentCommunityTransportError` with the original error as `__cause__`.
- Timeout during connection or tool call becomes `AgentCommunityTransportError` naming the operation and configured timeout, preserving the timeout cause.
- A tool result with `is_error=True` becomes `AgentCommunityToolError`, retaining bounded safe text from result content.
- A successful result without `structured_content` becomes `AgentCommunityProtocolError`.
- A model validation failure becomes `AgentCommunityProtocolError` and preserves the Pydantic validation error as cause.
- Cancellation is explicitly excluded from translation.

### Step 3: Run tests to verify failure

Run: `python -m pytest tests/test_client_lifecycle.py tests/test_client_errors.py -q`

Expected: FAIL because client/transport do not exist.

### Step 4: Implement lifecycle and one private typed-call primitive

In `_transport.py`, implement the minimum adapter around `mcp.Client(endpoint)`:

- Own async enter/exit and a single active high-level MCP client.
- Apply timeout to connect, close, and tool operations using cancellation-safe AnyIO/Python primitives compatible with Python 3.10.
- Translate transport failures while never catching `BaseException` or caller cancellation.
- Call tools using the public MCP SDK API.

In `client.py`, implement:

- Constructor validation and immutable configuration properties if needed for documentation/tests.
- Context management and idempotent `close()`.
- A private `_call_typed(tool_name, arguments, model_type)` that checks `is_error`, requires `structured_content`, and validates with the provided model.
- No public capability methods yet beyond private hooks needed for lifecycle tests.

Bound diagnostic text to a conservative maximum and do not include raw internal objects. Preserve causes with `raise ... from error`.

Update exports to include `AgentCommunityClient`. Do not expose the raw client/session or private transport.

### Step 5: Verify and commit

Run:

```bash
python -m pytest tests/test_client_lifecycle.py tests/test_client_errors.py -q
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src tests
```

Expected: all pass.

```bash
git add src/agentcommunity tests/fakes.py tests/test_client_lifecycle.py tests/test_client_errors.py
git commit -m "feat: add asynchronous MCP client lifecycle"
```

## Task 4: Add the three typed methods and real MCP-stack integration tests

**Files:**

- Modify: `src/agentcommunity/client.py`
- Modify: `tests/fakes.py`
- Create: `tests/test_client_methods.py`
- Create: `tests/test_mcp_integration.py`
- Create: `tests/test_contract_compatibility.py`

### Step 1: Write failing public-method tests

Test exact tool calls and typed returns:

- `community_stats()` calls `get_community_stats` with `{}` and returns `CommunityStats`.
- `lookup_member(query)` trims input, calls `lookup_member` with the trimmed value, and returns `MemberLookup`.
- Lookup accepts exactly 1 and 200 trimmed characters; empty/whitespace, 201 characters, non-string values, and malformed local input fail before transport.
- `verify_certificate(certificate_id)` passes strings through unchanged—including malformed identifiers—and returns `CertificateVerification` for all four states.
- Non-string certificate IDs fail locally, but no certificate-format regex exists.
- Malformed structured output for each method becomes `AgentCommunityProtocolError`.
- An extra/unrelated tool in server discovery does not affect any method.
- `AgentCommunityClient` has no `register_agent`, raw client, session, one-shot, or sync method/property.

### Step 2: Write failing contract-compatibility tests

Read the pinned fixture and verify:

- Each method's emitted argument dictionary satisfies its input schema constraints.
- Every fixture-defined valid output shape maps directly to the corresponding public model fields.
- Model required fields, status literals, match maximum, date/URL types, and certificate nullable fields remain aligned with the fixture.
- The package wraps only the three approved tool names even though `register_agent` exists in the contract.

Avoid a general JSON Schema code generator. The contract tests should clearly identify drift while keeping handwritten public models readable.

### Step 3: Write a failing official-stack integration test

Use the official MCP SDK's supported in-process/local server and client facilities to exercise a deterministic local endpoint through the actual `mcp.Client` code path. Register read-only test implementations of the three supported tools with structured outputs, then prove:

- One client connection performs all three calls.
- Results become the public typed models.
- Lifecycle closes cleanly.

Do not call production and do not register the unsafe `register_agent` tool.

If the SDK's supported in-memory transport cannot be passed through the public high-level client used in production, use a loopback Streamable HTTP server bound to an ephemeral port with reliable startup/cleanup. Do not replace the integration with a mocked fake.

### Step 4: Implement the exact public methods

Add only:

- `community_stats`
- `lookup_member`
- `verify_certificate`

Each delegates to `_call_typed`. Keep validation small and explicit. Do not list tools as a prerequisite for calls; runtime tolerance of additional tools follows from calling only known names.

### Step 5: Verify and commit

Run:

```bash
python -m pytest tests/test_client_methods.py tests/test_contract_compatibility.py tests/test_mcp_integration.py -q
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests
```

Expected: all pass with no network access.

```bash
git add src/agentcommunity/client.py tests
git commit -m "feat: wrap read-only Agent Community tools"
```

## Task 5: Complete documentation, CI, release, and artifact verification

**Files:**

- Create: `README.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `CHANGELOG.md`
- Create: `LICENSE`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/production-smoke.yml`
- Create: `.github/workflows/publish.yml`
- Create: `tests/test_public_api.py`
- Create: `tests/test_readme_examples.py`
- Create: `tests/smoke/test_production.py`
- Create: `scripts/verify-artifacts.sh`
- Modify: `pyproject.toml`

### Step 1: Write failing public-surface and README tests

Add tests that:

- Assert `agentcommunity.__all__` exactly contains `__version__`, `AgentCommunityClient`, four result models, and four exceptions.
- Assert no `register_agent`, sync facade, one-shot helper, raw MCP client/session, or CLI entry point is public.
- Extract or import the README's main async example and execute it against the deterministic private test transport/server without production network access.
- Validate project metadata includes the official homepage/source/docs/issues URLs, Python floor, dependency bounds, license, and typed marker.

Keep production smoke tests excluded by default with an explicit marker/configuration.

### Step 2: Create user and contributor documentation

Write a concise README covering installation, a complete async example, lifecycle reuse, all three methods/models, exception handling, endpoint/timeout overrides, support policy, and links. State clearly that registration is intentionally omitted because it requires explicit user authorization.

Add:

- MIT `LICENSE`.
- `SECURITY.md` with private disclosure instructions and supported-version policy.
- `CONTRIBUTING.md` with environment setup and the full local gate.
- `CHANGELOG.md` with an unreleased/0.1.0 entry describing the initial read-only SDK.

Do not claim the package is already available on PyPI or that the website already advertises it.

### Step 3: Add deterministic CI and optional production smoke

`ci.yml` must run on pull requests and pushes, with separate coverage for:

- Python 3.10 and latest stable Python.
- Lowest-direct-dependency bounds and newest allowed dependencies.
- Ruff check/format, strict mypy, full pytest, build, and Twine check.
- Clean wheel installation/import and source-distribution installation.
- Running the artifact verifier against the exact built files.

`production-smoke.yml` must be scheduled and manually dispatchable only. It calls read-only production methods, has a short timeout, no secrets, no registration, and is not referenced as a required pull-request check.

`publish.yml` must:

- Trigger on version tags or an appropriately protected manual flow.
- Build wheel/sdist once.
- Verify those exact files in a separate clean job/environment.
- Publish the unchanged downloaded artifacts with PyPI Trusted Publishing (`id-token: write`) and provenance.
- Store no token and contain no TestPyPI/PyPI credential placeholder.

### Step 4: Implement and exercise artifact verification

Create `scripts/verify-artifacts.sh` as a strict, portable Bash script that accepts an artifact directory, creates temporary isolated virtual environments, then:

- Runs `twine check` on wheel and source distribution.
- Installs the wheel without the source tree on `PYTHONPATH`, imports the exact public surface, checks version, and runs a minimal deterministic fake/local example.
- Installs the source distribution in another clean environment and performs the same import/public-surface check.
- Always cleans temporary directories.

Do not publish or contact package registries.

### Step 5: Run the full local release gate

Run from a clean working tree after deleting old artifacts:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests
python -m pytest -q
python -m build
python -m twine check dist/*
bash scripts/verify-artifacts.sh dist
```

Also inspect wheel and source distribution contents and verify no secrets, caches, tests-only helpers, or unexpected files ship. The pinned contract fixture may remain test-only and should not ship in the wheel.

Expected: all pass.

### Step 6: Commit

```bash
git add README.md SECURITY.md CONTRIBUTING.md CHANGELOG.md LICENSE .github scripts tests pyproject.toml
git commit -m "chore: prepare SDK release pipeline"
```

## Final verification and review

After every task has passed its specification and code-quality reviews:

1. Run the full local release gate again from current HEAD.
2. Run `git diff --check main...HEAD` and inspect `git diff --stat main...HEAD` plus the complete diff.
3. Dispatch `superpowers:requesting-code-review` using base SHA from `main` and current HEAD.
4. Resolve every Critical and Important finding, rerun affected and full checks, and request re-review when necessary.
5. Apply `superpowers:verification-before-completion` before claiming success.
6. Apply `superpowers:finishing-a-development-branch` and present the four integration choices. Do not create a remote, push, open a pull request, configure PyPI, publish, or modify the website without explicit user authorization.

