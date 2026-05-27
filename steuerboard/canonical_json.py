from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_sha256(payload: Any) -> str:
    """Return lowercase SHA-256 over canonical UTF-8 JSON bytes."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
