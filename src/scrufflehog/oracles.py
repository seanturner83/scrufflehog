"""The assertion oracles — the universal, language-independent core.

Given a redactor's OUTPUT STRING and the probe that produced it, decide whether
the redaction was effective. These functions know nothing about how the output
was produced (Python import, compiled Go driver, ...), which is what lets one
set of checks verify redactors in any language.

Three defect classes:
  literal_survival — the secret appears verbatim in the output.
  noop_passthrough — the output equals the (sensitive) input, unchanged.
  reversible       — the output is a deterministic, keyless, low-entropy
                     transform of a candidate in the probe's secret_space, so the
                     plaintext is recoverable. Bounded by secret_space; never an
                     unbounded crack.
"""
from __future__ import annotations

import hashlib
from base64 import b64encode
from dataclasses import dataclass

from .probes import Probe


@dataclass
class Defect:
    redactor: str          # label, e.g. "module:fn" or "module:symbol"
    klass: str             # one of the class keys below
    probe: str             # probe name (or a synthetic marker)
    detail: str


LITERAL_SURVIVAL = "literal_survival"
NOOP_PASSTHROUGH = "noop_passthrough"
REVERSIBLE = "reversible"
COVERAGE_GAP = "coverage_gap"
REDACTOR_ERRORED = "redactor_errored"


def _sha_prefixes(v: str) -> set[str]:
    """Every truncated-and-full SHA-256 prefix a truncating redactor might emit
    (6..64 hex). Lets us catch `sha256(v)[:10]`-style markers."""
    full = hashlib.sha256(v.encode()).hexdigest()
    return {full[:n] for n in range(6, 65)}


def reversible(output: str, space: list[str]) -> str | None:
    """Return the recovered plaintext if `output` deterministically encodes a
    candidate in `space` via a keyless weak transform; else None.

    Transforms probed (all reproducible by an attacker — no salt, no key):
      - identity / substring
      - truncated or full unsalted SHA-256
      - base64 (padded or not)
    Only candidates in `space` are tried, so cost is bounded and we never claim
    a high-entropy value is reversible.
    """
    if not space or not isinstance(output, str):
        return None
    for cand in space:
        if cand and cand in output:
            return cand
        if any(pref in output for pref in _sha_prefixes(cand)):
            return cand
        enc = b64encode(cand.encode()).decode()
        if enc in output or enc.rstrip("=") in output:
            return cand
    return None


def assert_output(output: str, probe: Probe, label: str, kind: str) -> Defect | None:
    """Apply the three oracles to a redactor's output. Return the first defect
    found (most severe first: literal > no-op > reversible), or None if clean."""
    # 1. literal survival — the secret is right there.
    if probe.secret and probe.secret in output:
        return Defect(label, LITERAL_SURVIVAL, probe.name,
                      "secret survives verbatim in output")

    # 2. no-op passthrough — output unchanged for a sensitive value input.
    if probe.sensitive and kind in ("value", "row"):
        in_str = probe.input if (kind == "value" and isinstance(probe.input, str)) else None
        if in_str is not None and output.strip() == in_str.strip():
            return Defect(label, NOOP_PASSTHROUGH, probe.name,
                          "redactor returned input unchanged")

    # 3. reversibility — bounded oracle over the probe's secret_space.
    rec = reversible(output, probe.secret_space)
    if rec is not None:
        return Defect(label, REVERSIBLE, probe.name,
                      f"output is a keyless/unsalted transform; recovered "
                      f"{rec!r} from a {len(probe.secret_space)}-candidate space")
    return None
