from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_sha256(payload: Any) -> str:
    """Return the lowercase hex SHA-256 digest of a JSON-serialisable payload.

    The payload is serialised with ``sort_keys=True``, ``separators=(",", ":")``
    and ``ensure_ascii=False``, then UTF-8 encoded.  Equal Python objects always
    produce equal digests so plan-binding checks across artifacts compare exactly.
    This is the one canonical hash used for action-plan / approval / run-result
    binding; do not introduce a second implementation.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
