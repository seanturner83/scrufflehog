"""Engine — ties runners + coverage + oracles into a verification run.

Two families:
  transform-strength — execute each registered redactor on its probe set,
                       apply the oracles to the output.
  coverage           — statically extract each denylist/allow-list and check a
                       sensitive-field corpus against it.

The advisor (default no-op) may add probes, discover redactors, or confirm
coverage gaps — but the deterministic oracle renders every verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .advisor import Advisor, CoverageVerdict, NoopAdvisor
from .coverage import covered, extract_key_set, DEFAULT_SENSITIVE_FIELDS
from .oracles import (COVERAGE_GAP, REDACTOR_ERRORED, Defect, assert_output)
from .probes import Probe, get_probe_set
from .runners import make_producer


@dataclass
class RunResult:
    defects: list[Defect] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _transform_probes(target: Path, entry: dict, advisor: Advisor) -> list[Probe]:
    """Assemble the probe set for a redactor.

    probe_set semantics:
      "advisor" — the advisor SUPPLIES the probe set (replace mode). Use for a
                  redactor whose input domain is best inferred from its source
                  (e.g. a URL-scoped redactor, where the generic value probes are
                  out-of-contract and would false-positive). The advisor is still
                  only choosing INPUTS, never verdicts — the oracle judges what
                  runs. If the advisor yields nothing (no backend / parse fail),
                  we fall back to the built-in "value" set so the redactor is
                  never left un-probed (fail-safe: never silently skip).
      other     — additive: the named built-in set PLUS any advisor probes. Safe
                  default; the advisor can only add signal, never hide a defect.
    """
    src = ""
    mod = entry.get("module")
    if mod and (target / mod).exists():
        try:
            src = (target / mod).read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""

    name = entry.get("probe_set", "value")
    if name == "advisor":
        try:
            supplied = advisor.propose_probes(src, entry)
        except Exception:  # noqa: BLE001
            supplied = []
        # Fail-safe: an advisor that produced nothing must not leave the redactor
        # untested — fall back to the generic set rather than "clean by omission".
        return supplied if supplied else get_probe_set("value")

    probes = get_probe_set(name)
    try:
        probes = probes + advisor.propose_probes(src, entry)
    except Exception:  # noqa: BLE001 — advisor failure degrades to deterministic
        pass
    return probes


def verify_transform(target: Path, entry: dict, advisor: Advisor) -> tuple[list[Defect], str]:
    lang = entry.get("lang", "python")
    label = f"{entry.get('module', '?')}:{entry.get('fn', '?')}"
    kind = entry.get("kind", "value")
    try:
        produce = make_producer(target, entry)
    except (FileNotFoundError, AttributeError, RuntimeError, ValueError, ImportError) as e:
        return ([Defect(label, REDACTOR_ERRORED, "-",
                        f"[{lang}] could not prepare redactor: {e}")],
                f"[transform:{lang}] {label}: unprepared")
    probes = _transform_probes(target, entry, advisor)
    defects: list[Defect] = []
    try:
        for p in probes:
            try:
                out = produce(p)
            except Exception as exc:  # noqa: BLE001 — a crashing redactor IS a defect
                defects.append(Defect(label, REDACTOR_ERRORED, p.name,
                                      f"redactor raised {type(exc).__name__}: {exc}"))
                continue
            d = assert_output(out, p, label, kind)
            if d is not None:
                defects.append(d)
    finally:
        cleanup = getattr(produce, "_cleanup", None)
        if callable(cleanup):
            cleanup()
    return defects, f"[transform:{lang}] {label}: {len(defects)} defect(s)"


def verify_coverage(target: Path, spec: dict, advisor: Advisor) -> tuple[list[Defect], str]:
    label = f"{spec['module']}:{spec['symbol']}"
    try:
        keys = extract_key_set(target, spec)
    except (FileNotFoundError, ValueError) as e:
        return ([Defect(label, REDACTOR_ERRORED, "-",
                        f"coverage target did not resolve: {e}")],
                f"[coverage] {label}: unresolved")
    match = spec.get("match", "exact_ci")
    corpus = spec.get("corpus", DEFAULT_SENSITIVE_FIELDS)
    defects: list[Defect] = []
    for f in corpus:
        if covered(f, keys, match):
            continue
        # Advisor may confirm/refute the hypothesis; default leaves it standing.
        try:
            verdict = advisor.confirm_coverage_gap(target, f, label)
        except Exception:  # noqa: BLE001
            verdict = CoverageVerdict.UNCONFIRMED
        if verdict == CoverageVerdict.REFUTED:
            continue
        suffix = "" if verdict == CoverageVerdict.UNCONFIRMED else f" [{verdict}]"
        defects.append(Defect(
            label, COVERAGE_GAP, f,
            f"sensitive field {f!r} not caught by the {len(keys)}-key list "
            f"under {match} matching — it is not redacted{suffix}"))
    if spec.get("doc_claims_substring") and match == "exact_ci" and defects:
        defects.append(Defect(
            label, COVERAGE_GAP, "<doc-mismatch>",
            "redactor docs claim partial/substring matching but the behaviour is "
            "exact — fields expected to be covered by substring are NOT"))
    return defects, f"[coverage] {label}: {len(defects)} gap(s)"


def run(target: Path, config: dict[str, Any], advisor: Advisor | None = None) -> RunResult:
    """Run all transform + coverage checks in `config` against `target`.

    config = {"transform": [entry, ...], "coverage": [spec, ...]}
    """
    advisor = advisor or NoopAdvisor()
    result = RunResult()

    transform = config.get("transform", [])
    coverage = config.get("coverage", [])
    if not transform and not coverage:
        result.notes.append("no redactors configured — nothing to verify")
        return result

    for entry in transform:
        defects, note = verify_transform(target, entry, advisor)
        result.defects.extend(defects)
        result.notes.append(note)
    for spec in coverage:
        defects, note = verify_coverage(target, spec, advisor)
        result.defects.extend(defects)
        result.notes.append(note)
    return result
