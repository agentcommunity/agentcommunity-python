import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def contract_bytes() -> bytes:
    contract_path = Path(__file__).parent / "contracts" / "1.5.0" / "mcp.json"
    return contract_path.read_bytes()


@pytest.fixture
def contract(contract_bytes: bytes) -> dict[str, Any]:
    parsed = json.loads(contract_bytes)
    assert isinstance(parsed, dict)
    return parsed
