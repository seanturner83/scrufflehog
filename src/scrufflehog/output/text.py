"""Human-readable output."""
from __future__ import annotations

from ..engine import RunResult


def render_text(result: RunResult, target: str) -> str:
    lines = [f"scrufflehog — {target}", ""]
    lines.append(f"defects: {len(result.defects)}")
    for n in result.notes:
        lines.append(f"  {n}")
    if result.defects:
        lines.append("")
        for d in result.defects:
            lines.append(f"  [{d.klass}] {d.redactor} ({d.probe}): {d.detail}")
    else:
        lines.append("  no redaction defects found")
    return "\n".join(lines)
