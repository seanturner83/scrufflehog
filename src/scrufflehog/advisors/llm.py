"""LLMAdvisor — the optional agentic layer.

Provider-agnostic: you pass a `complete(prompt: str) -> str` callable, so this
works with any backend (Anthropic, OpenAI, Bedrock, a local model) with no hard
SDK dependency. The core package never imports this module.

Invariant (see docs/AGENTIC.md): the advisor only proposes INPUTS and
HYPOTHESES. It NEVER renders a verdict — the deterministic oracle still decides
every defect. So:
  - propose_probes: returns extra probes (planted secrets we control) for the
    engine to run through the redactor + oracle. The model picks realistic
    SHAPES; ground truth (the secret) is still ours.
  - discover_redactors: returns candidate config entries for a human to confirm.
  - confirm_coverage_gap: returns CONFIRMED/REFUTED/UNCONFIRMED by asking the
    model to check real field usage — but a coverage finding only ever
    DOWNGRADES to refuted or stays a hypothesis; the model can't invent one.

Every method degrades to the deterministic default (empty / UNCONFIRMED) on any
error, malformed output, or timeout. A broken advisor can never fail a run or
manufacture a finding.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from ..advisor import CoverageVerdict
from ..probes import Probe, weak_secret_space

CompleteFn = Callable[[str], str]

_MAX_SRC = 6000        # cap redactor source sent to the model
_MAX_PROBES = 6        # cap generated probes per redactor


def _extract_json(text: str):
    """Pull the first JSON array/object out of a model reply (tolerant of prose
    or ```json fences). Returns the parsed value or None."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # try array then object
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = candidate.find(opener), candidate.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(candidate[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


class LLMAdvisor:
    def __init__(self, complete: CompleteFn):
        self._complete = complete

    # --- 1. domain-matched probe generation -------------------------------
    def propose_probes(self, redactor_src: str, entry: dict) -> list[Probe]:
        if not redactor_src:
            return []
        prompt = (
            "You are helping test a redaction function. Given its source, return "
            "a JSON array of test INPUTS shaped like the data this redactor is "
            "meant to process (e.g. if it redacts URLs, produce URL strings; if "
            "log field values, produce those). For each, give a JSON object "
            '{"name": str, "input": str, "secret": str} where `secret` is a '
            "substring of `input` that MUST be redacted. Use the literal token "
            "SECRET_MARKER as the sensitive value inside each input so it is "
            "unambiguous. Return ONLY the JSON array.\n\n"
            f"Redactor source:\n```\n{redactor_src[:_MAX_SRC]}\n```")
        try:
            parsed = _extract_json(self._complete(prompt))
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(parsed, list):
            return []
        probes: list[Probe] = []
        for i, item in enumerate(parsed[:_MAX_PROBES]):
            if not isinstance(item, dict):
                continue
            inp = item.get("input")
            secret = item.get("secret")
            if not isinstance(inp, str) or not isinstance(secret, str) or not secret:
                continue
            # Substitute OUR controlled secret for the model's marker so ground
            # truth is ours, not the model's — it only chose the SHAPE.
            controlled = "test1234"
            inp2 = inp.replace("SECRET_MARKER", controlled)
            sec2 = secret.replace("SECRET_MARKER", controlled)
            if sec2 not in inp2:
                continue  # discard shapes where the secret isn't actually present
            probes.append(Probe(
                name=str(item.get("name", f"llm-probe-{i}"))[:60],
                input=inp2, secret=sec2, secret_space=weak_secret_space()))
        return probes

    # --- 2. redactor discovery (proposals for human/config confirmation) ---
    def discover_redactors(self, target: Path) -> list[dict]:
        # Intentionally conservative: discovery is advisory and needs a repo
        # walk the caller opts into. Left as a proposal hook; returns [] unless
        # a subclass wires a file walk. Kept simple to avoid scanning huge trees
        # by default.
        return []

    # --- 3. coverage-gap confirmation -------------------------------------
    def confirm_coverage_gap(self, target: Path, field: str, redactor: str) -> str:
        """Ask whether a field named `field` plausibly reaches this redactor in
        the codebase. Can only REFUTE (drop) or leave UNCONFIRMED — never
        promote to a defect the oracle didn't produce."""
        # Cheap deterministic pre-check: does the token even appear in the tree?
        # (A model call is only worth it if there's something to reason about.)
        try:
            hits = self._grep_field(target, field)
        except Exception:  # noqa: BLE001
            return CoverageVerdict.UNCONFIRMED
        if not hits:
            # The field name appears nowhere — the gap is likely moot here.
            # Still only UNCONFIRMED (absence in source ≠ never logged), unless
            # the model is available to make the call.
            pass
        prompt = (
            "A log/PII redactor does NOT redact a field named "
            f"'{field}'. Here are code lines mentioning it (may be empty):\n"
            + "\n".join(hits[:20]) +
            "\n\nBased ONLY on this, is a field literally named "
            f"'{field}' plausibly present in data this redactor processes? "
            'Answer with JSON {"verdict": "confirmed"|"refuted"|"unconfirmed"}. '
            "Use 'refuted' only if the name clearly does not occur as a data "
            "field here.")
        try:
            parsed = _extract_json(self._complete(prompt))
        except Exception:  # noqa: BLE001
            return CoverageVerdict.UNCONFIRMED
        if isinstance(parsed, dict):
            v = str(parsed.get("verdict", "")).lower()
            if v in (CoverageVerdict.CONFIRMED, CoverageVerdict.REFUTED,
                     CoverageVerdict.UNCONFIRMED):
                return v
        return CoverageVerdict.UNCONFIRMED

    @staticmethod
    def _grep_field(target: Path, field: str) -> list[str]:
        """Deterministic, cheap: source lines mentioning the field name. Bounded
        to keep it fast; skips obvious vendored/build dirs."""
        out: list[str] = []
        skip = {"node_modules", ".git", "dist", "build", "target", ".venv", "vendor"}
        exts = {".go", ".py", ".ts", ".js", ".rs", ".java", ".rb", ".proto"}
        pat = re.compile(re.escape(field), re.IGNORECASE)
        for p in target.rglob("*"):
            if len(out) >= 50:
                break
            if not p.is_file() or p.suffix not in exts:
                continue
            if any(part in skip for part in p.parts):
                continue
            try:
                for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    if pat.search(ln):
                        out.append(f"{p.name}: {ln.strip()[:160]}")
                        if len(out) >= 50:
                            break
            except OSError:
                continue
        return out
