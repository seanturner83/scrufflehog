"""Machine-readable JSON output."""
from __future__ import annotations

import json
from dataclasses import asdict

from ..engine import RunResult


def render_json(result: RunResult, target: str) -> str:
    return json.dumps({
        "target": target,
        "defect_count": len(result.defects),
        "defects": [asdict(d) for d in result.defects],
        "notes": result.notes,
    }, indent=2)
