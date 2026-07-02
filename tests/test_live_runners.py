"""Live cross-language runner tests — actually build + run fixture redactors in
Go / Node / Rust through the runners, and assert the oracles catch the planted
secret. Skipped when the toolchain is absent so the core suite stays portable.

Each fixture is a MINIMAL, self-contained redactor with a deliberate weakness
(no-op or truncated hash), proving the compiled-driver path end-to-end — not
just the source-shape.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scrufflehog import oracles  # noqa: E402
from scrufflehog.probes import Probe  # noqa: E402
from scrufflehog.runners import make_producer  # noqa: E402

HAVE_GO = shutil.which("go") is not None
HAVE_NODE = shutil.which("node") is not None
HAVE_CARGO = shutil.which("cargo") is not None


def _run_one(target: Path, entry: dict, probe: Probe, kind="value"):
    produce = make_producer(target, entry)
    try:
        out = produce(probe)
        return oracles.assert_output(out, probe, "fixture", kind), out
    finally:
        cleanup = getattr(produce, "_cleanup", None)
        if callable(cleanup):
            cleanup()


# ---- Go -------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_GO, reason="go toolchain not installed")
def test_go_noop_redactor_caught(tmp_path):
    (tmp_path / "go.mod").write_text("module example.test/fixture\n\ngo 1.21\n")
    pkg = tmp_path / "redact"
    pkg.mkdir()
    # A no-op "redactor" — returns input unchanged.
    (pkg / "redact.go").write_text(
        "package redact\n\nfunc Mask(s string) string {\n\treturn s\n}\n")
    entry = {"lang": "go", "module": "redact",
             "import": "example.test/fixture/redact", "fn": "Mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry, Probe("p", "test1234", "test1234"))
    assert out == "test1234"
    assert defect and defect.klass in (oracles.LITERAL_SURVIVAL, oracles.NOOP_PASSTHROUGH)


@pytest.mark.skipif(not HAVE_GO, reason="go toolchain not installed")
def test_go_strong_redactor_clean(tmp_path):
    (tmp_path / "go.mod").write_text("module example.test/fixture\n\ngo 1.21\n")
    pkg = tmp_path / "redact"
    pkg.mkdir()
    (pkg / "redact.go").write_text(
        'package redact\n\nfunc Mask(s string) string {\n\treturn "<redacted>"\n}\n')
    entry = {"lang": "go", "module": "redact",
             "import": "example.test/fixture/redact", "fn": "Mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry,
                           Probe("p", "test1234", "test1234", secret_space=["test1234"]))
    assert out == "<redacted>"
    assert defect is None


# ---- Node -----------------------------------------------------------------

@pytest.mark.skipif(not HAVE_NODE, reason="node runtime not installed")
def test_node_noop_redactor_caught(tmp_path):
    (tmp_path / "redact.js").write_text(
        "module.exports.mask = function (s) { return s; };\n")
    entry = {"lang": "node", "module": "redact.js", "fn": "mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry, Probe("p", "test1234", "test1234"))
    assert out == "test1234"
    assert defect and defect.klass in (oracles.LITERAL_SURVIVAL, oracles.NOOP_PASSTHROUGH)


@pytest.mark.skipif(not HAVE_NODE, reason="node runtime not installed")
def test_node_weak_base64_reversible(tmp_path):
    # "redaction" that just base64s the value — reversible.
    (tmp_path / "redact.js").write_text(
        "module.exports.mask = function (s) { "
        "return Buffer.from(s).toString('base64'); };\n")
    entry = {"lang": "node", "module": "redact.js", "fn": "mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry,
                           Probe("p", "test1234", "test1234", secret_space=["test1234"]))
    assert defect and defect.klass == oracles.REVERSIBLE


# ---- Rust -----------------------------------------------------------------

@pytest.mark.skipif(not HAVE_CARGO, reason="cargo toolchain not installed")
def test_rust_noop_redactor_caught(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "fixture"\nversion = "0.1.0"\nedition = "2021"\n'
        '[lib]\npath = "src/lib.rs"\n')
    src = tmp_path / "src"
    src.mkdir()
    # no-op redactor in the crate lib
    (src / "lib.rs").write_text(
        "pub fn mask(s: &str) -> String { s.to_string() }\n")
    entry = {"lang": "rust", "module": ".", "call": "fixture::mask(&line)"}
    defect, out = _run_one(tmp_path, entry, Probe("p", "test1234", "test1234"))
    assert out == "test1234"
    assert defect and defect.klass in (oracles.LITERAL_SURVIVAL, oracles.NOOP_PASSTHROUGH)
