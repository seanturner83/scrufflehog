"""LLMAdvisor tests with a FAKE completion backend — no network, deterministic.

Verifies the invariant: the advisor only supplies inputs/hypotheses; the
deterministic oracle still decides. A malformed or throwing backend degrades to
the deterministic default and never crashes or manufactures a defect.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scrufflehog.advisor import CoverageVerdict, NoopAdvisor  # noqa: E402
from scrufflehog.advisors.llm import LLMAdvisor, _extract_json  # noqa: E402
from scrufflehog.engine import run  # noqa: E402
from scrufflehog import oracles  # noqa: E402


def _fake(reply: str):
    return lambda prompt: reply


def test_extract_json_tolerates_fences_and_prose():
    assert _extract_json('here: ```json\n[1,2]\n``` ok') == [1, 2]
    assert _extract_json('{"verdict": "refuted"}') == {"verdict": "refuted"}
    assert _extract_json("no json here") is None


def test_propose_probes_substitutes_controlled_secret():
    reply = '[{"name":"url","input":"https://x/v2/SECRET_MARKER","secret":"SECRET_MARKER"}]'
    adv = LLMAdvisor(_fake(reply))
    probes = adv.propose_probes("func Sanitize(u string) string", {})
    assert len(probes) == 1
    p = probes[0]
    # our controlled secret replaced the model marker; secret is in the input
    assert "SECRET_MARKER" not in p.input
    assert p.secret in p.input
    assert p.secret == "test1234"


def test_propose_probes_discards_shapes_without_secret_present():
    reply = '[{"name":"bad","input":"nothing here","secret":"SECRET_MARKER"}]'
    adv = LLMAdvisor(_fake(reply))
    assert adv.propose_probes("src", {}) == []


def test_propose_probes_degrades_on_bad_json():
    adv = LLMAdvisor(_fake("not json at all"))
    assert adv.propose_probes("src", {}) == []


def test_propose_probes_degrades_on_backend_error():
    def boom(_):
        raise RuntimeError("api down")
    adv = LLMAdvisor(boom)
    assert adv.propose_probes("src", {}) == []


def test_confirm_coverage_gap_can_refute(tmp_path):
    adv = LLMAdvisor(_fake('{"verdict":"refuted"}'))
    assert adv.confirm_coverage_gap(tmp_path, "ssn", "x:y") == CoverageVerdict.REFUTED


def test_confirm_coverage_gap_defaults_unconfirmed_on_error(tmp_path):
    def boom(_):
        raise RuntimeError("x")
    adv = LLMAdvisor(boom)
    assert adv.confirm_coverage_gap(tmp_path, "ssn", "x:y") == CoverageVerdict.UNCONFIRMED


def test_advisor_can_only_downgrade_coverage_not_invent(tmp_path):
    """A refuting advisor DROPS a gap; it cannot add one. Compare against noop."""
    (tmp_path / "r.py").write_text('FIELDS = ["email"]\n')
    config = {"transform": [], "coverage": [
        {"module": "r.py", "symbol": "FIELDS", "extract": "py_collection",
         "match": "exact_ci", "corpus": ["email", "ssn"]}]}
    # noop: ssn is a gap
    noop_gaps = {d.probe for d in run(tmp_path, config, NoopAdvisor()).defects}
    assert "ssn" in noop_gaps
    # refuting advisor: ssn dropped
    refute = LLMAdvisor(_fake('{"verdict":"refuted"}'))
    ref_gaps = {d.probe for d in run(tmp_path, config, refute).defects}
    assert "ssn" not in ref_gaps


def test_advisor_added_probes_still_judged_by_oracle(tmp_path):
    """A probe the advisor supplies is run through the redactor + oracle. With a
    no-op redactor, the advisor's URL probe survives verbatim → a real defect,
    but ONLY because the deterministic oracle confirmed it."""
    (tmp_path / "r.py").write_text("def redact(s):\n    return s\n")  # no-op
    config = {"transform": [{"lang": "python", "module": "r.py", "fn": "redact",
                             "kind": "value"}], "coverage": []}
    reply = '[{"name":"u","input":"https://x/v2/SECRET_MARKER","secret":"SECRET_MARKER"}]'
    adv = LLMAdvisor(_fake(reply))
    result = run(tmp_path, config, adv)
    # the advisor's probe (named 'u') produced a deterministic literal_survival
    assert any(d.probe == "u" and d.klass == oracles.LITERAL_SURVIVAL
               for d in result.defects)
