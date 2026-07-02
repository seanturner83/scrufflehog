"""Tests for the generic scrufflehog core — oracles, coverage extraction,
engine, output. Uses synthetic fixtures written to tmp (no external repos)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scrufflehog import oracles, probes  # noqa: E402
from scrufflehog.coverage import extract, semantics  # noqa: E402
from scrufflehog.engine import run  # noqa: E402
from scrufflehog.output import render_json, render_sarif, render_text  # noqa: E402


# ---- oracles: reversibility ----------------------------------------------

def test_reversible_recovers_truncated_sha():
    v = "test1234"
    out = f"<redacted:{hashlib.sha256(v.encode()).hexdigest()[:10]}>"
    assert oracles.reversible(out, ["test1234", "other"]) == "test1234"


def test_reversible_none_for_constant_marker():
    assert oracles.reversible("<redacted>", ["test1234", "password"]) is None


def test_reversible_skipped_without_space():
    out = hashlib.sha256(b"highentropykey").hexdigest()[:10]
    assert oracles.reversible(out, []) is None


def test_reversible_catches_base64():
    import base64
    v = "password"
    out = f"x{base64.b64encode(v.encode()).decode()}x"
    assert oracles.reversible(out, ["password"]) == "password"


# ---- oracles: assert_output ----------------------------------------------

def _p(value, secret, space=None):
    return probes.Probe("p", value, secret, secret_space=space or [])


def test_literal_survival():
    d = oracles.assert_output("email is a@b.com", _p("a@b.com", "a@b.com"), "x:f", "value")
    assert d and d.klass == oracles.LITERAL_SURVIVAL


def test_noop_passthrough():
    d = oracles.assert_output("secret", _p("secret", "unrelated"), "x:f", "value")
    assert d and d.klass == oracles.NOOP_PASSTHROUGH


def test_clean_output_no_defect():
    d = oracles.assert_output("<redacted>", _p("secret", "secret"), "x:f", "value")
    assert d is None


# ---- coverage: semantics --------------------------------------------------

def test_match_semantics():
    keys = {"email", "account"}
    assert semantics.covered("Email", keys, "exact_ci")
    assert not semantics.covered("email_address", keys, "exact_ci")
    assert semantics.covered("email_address", keys, "substring_ci")


# ---- coverage: extractors -------------------------------------------------

def _write(tmp: Path, rel: str, content: str) -> Path:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return tmp


def test_extract_go_map_skips_comment_and_struct_brace(tmp_path):
    src = ('// SecretKeys is the list.\n'
           'var SecretKeys = map[string]struct{}{\n'
           '\t"password": {},\n\t"email": {},\n}\n')
    root = _write(tmp_path, "k.go", src)
    keys = extract.extract_key_set(root, {"module": "k.go", "symbol": "SecretKeys",
                                          "extract": "go_map_keys"})
    assert keys == {"password", "email"}


def test_extract_py_collection(tmp_path):
    root = _write(tmp_path, "r.py", 'SECRET_FIELDS = ["ssn", "cvv", \'iban\']\n')
    keys = extract.extract_key_set(root, {"module": "r.py", "symbol": "SECRET_FIELDS",
                                          "extract": "py_collection"})
    assert keys == {"ssn", "cvv", "iban"}


def test_extract_ts_redact_paths_leaves(tmp_path):
    src = ("const o = { redact: { paths: [\n"
           "  redact.req('body.email'),\n"
           "  redact.res('body.message[*].phone_number'),\n"
           "  'req.headers.authorization',\n] } }\n")
    root = _write(tmp_path, "logger.ts", src)
    keys = extract.extract_key_set(root, {"module": "logger.ts", "symbol": "redact",
                                          "extract": "ts_redact_paths"})
    assert keys == {"email", "phone_number", "authorization"}


def test_extract_empty_fails_loud(tmp_path):
    root = _write(tmp_path, "k.go", "var SecretKeys = map[string]struct{}{\n}\n")
    with pytest.raises(ValueError):
        extract.extract_key_set(root, {"module": "k.go", "symbol": "SecretKeys",
                                       "extract": "go_map_keys"})


# ---- engine: end-to-end with a python fixture redactor --------------------

def test_engine_python_transform_catches_noop(tmp_path):
    _write(tmp_path, "app/redact.py", "def redact_value(s):\n    return s\n")
    config = {"transform": [{"lang": "python", "module": "app/redact.py",
                             "fn": "redact_value", "kind": "value"}], "coverage": []}
    result = run(tmp_path, config)
    assert any(d.klass in (oracles.LITERAL_SURVIVAL, oracles.NOOP_PASSTHROUGH)
               for d in result.defects)


def test_engine_python_transform_clean(tmp_path):
    _write(tmp_path, "app/redact.py",
           "def redact_value(s):\n    return '<redacted>'\n")
    config = {"transform": [{"lang": "python", "module": "app/redact.py",
                             "fn": "redact_value", "kind": "value"}], "coverage": []}
    result = run(tmp_path, config)
    assert result.defects == []


def test_engine_python_transform_weak_hash_reversible(tmp_path):
    _write(tmp_path, "app/redact.py",
           "import hashlib\n"
           "def redact_value(s):\n"
           "    return '<' + hashlib.sha256(s.encode()).hexdigest()[:10] + '>'\n")
    config = {"transform": [{"lang": "python", "module": "app/redact.py",
                             "fn": "redact_value", "kind": "value"}], "coverage": []}
    result = run(tmp_path, config)
    assert any(d.klass == oracles.REVERSIBLE for d in result.defects)


def test_engine_coverage_gap(tmp_path):
    _write(tmp_path, "app/redact.py", 'SECRET_FIELDS = ["email", "tax_id"]\n')
    config = {"transform": [], "coverage": [
        {"module": "app/redact.py", "symbol": "SECRET_FIELDS",
         "extract": "py_collection", "match": "exact_ci",
         "corpus": ["email", "ssn", "cvv"]}]}
    result = run(tmp_path, config)
    gaps = {d.probe for d in result.defects if d.klass == oracles.COVERAGE_GAP}
    assert "email" not in gaps            # covered
    assert {"ssn", "cvv"}.issubset(gaps)  # gaps


def test_engine_empty_config_is_noop(tmp_path):
    result = run(tmp_path, {"transform": [], "coverage": []})
    assert result.defects == []
    assert any("nothing to verify" in n for n in result.notes)


# ---- output ---------------------------------------------------------------

def test_outputs_render(tmp_path):
    _write(tmp_path, "app/redact.py", "def redact_value(s):\n    return s\n")
    config = {"transform": [{"lang": "python", "module": "app/redact.py",
                             "fn": "redact_value", "kind": "value"}], "coverage": []}
    result = run(tmp_path, config)
    assert "scrufflehog" in render_text(result, ".")
    j = json.loads(render_json(result, "."))
    assert j["defect_count"] == len(result.defects)
    s = json.loads(render_sarif(result, "."))
    assert s["version"] == "2.1.0"
    assert s["runs"][0]["results"]


# ---- determinism invariant -----------------------------------------------

def test_deterministic_repeat(tmp_path):
    _write(tmp_path, "app/redact.py", "def redact_value(s):\n    return s\n")
    config = {"transform": [{"lang": "python", "module": "app/redact.py",
                             "fn": "redact_value", "kind": "value"}], "coverage": []}
    a = render_json(run(tmp_path, config), ".")
    b = render_json(run(tmp_path, config), ".")
    assert a == b
