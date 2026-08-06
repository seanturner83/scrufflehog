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
def test_go_unexported_redactor_is_reachable(tmp_path):
    """Idiomatic Go keeps redaction helpers PACKAGE-PRIVATE, so a driver in its own
    package cannot call them. Measured on a real fleet: 11 of 12 redactors written
    by an automated remediator were unexported, and every one came back
    `redactor_errored: go build failed` — i.e. the tool was blind to ~92% of the
    population it was pointed at.

    Both pre-existing Go fixtures used `func Mask` (exported), which is why this
    gap survived. The producer now falls back to an IN-PACKAGE test driver.
    """
    (tmp_path / "go.mod").write_text("module example.test/fixture\n\ngo 1.21\n")
    pkg = tmp_path / "redact"
    pkg.mkdir()
    # lowercase = unexported: invisible to any other package
    (pkg / "redact.go").write_text(
        "package redact\n\nfunc mask(s string) string {\n\treturn s\n}\n")
    entry = {"lang": "go", "module": "redact",
             "import": "example.test/fixture/redact", "fn": "mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry, Probe("p", "test1234", "test1234"))
    assert out == "test1234"
    assert defect and defect.klass in (oracles.LITERAL_SURVIVAL,
                                       oracles.NOOP_PASSTHROUGH)


@pytest.mark.skipif(not HAVE_GO, reason="go toolchain not installed")
def test_go_unexported_strong_redactor_clean(tmp_path):
    """The in-package path must also produce a TRUE NEGATIVE, not just find faults."""
    (tmp_path / "go.mod").write_text("module example.test/fixture\n\ngo 1.21\n")
    pkg = tmp_path / "redact"
    pkg.mkdir()
    (pkg / "redact.go").write_text(
        'package redact\n\nfunc mask(s string) string {\n\treturn "<redacted>"\n}\n')
    entry = {"lang": "go", "module": "redact",
             "import": "example.test/fixture/redact", "fn": "mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry,
                           Probe("p", "test1234", "test1234", secret_space=["test1234"]))
    assert out == "<redacted>"
    assert defect is None


@pytest.mark.skipif(not HAVE_GO, reason="go toolchain not installed")
def test_go_unexported_leaves_no_driver_behind(tmp_path):
    """The in-package driver is written INTO the target's source tree, so failing to
    remove it would leave a stray _test.go in someone's repo."""
    (tmp_path / "go.mod").write_text("module example.test/fixture\n\ngo 1.21\n")
    pkg = tmp_path / "redact"
    pkg.mkdir()
    (pkg / "redact.go").write_text(
        "package redact\n\nfunc mask(s string) string {\n\treturn s\n}\n")
    entry = {"lang": "go", "module": "redact",
             "import": "example.test/fixture/redact", "fn": "mask", "kind": "value"}
    _run_one(tmp_path, entry, Probe("p", "test1234", "test1234"))
    strays = list(pkg.glob("*scrufflehog*"))
    assert strays == [], f"driver left behind: {strays}"


@pytest.mark.skipif(not HAVE_GO, reason="go toolchain not installed")
def test_go_internal_package_is_reachable(tmp_path):
    """A SECOND reason the external driver fails, and it has nothing to do with
    export: Go's `internal/` rule forbids the import outright ("use of internal
    package ... not allowed"), so even an EXPORTED redactor under internal/ is
    unreachable. Measured on a real fleet — this is what blocked
    movements-command's `internal/service/config`. The in-package driver answers
    both cases."""
    (tmp_path / "go.mod").write_text("module example.test/fixture\n\ngo 1.21\n")
    pkg = tmp_path / "internal" / "redact"
    pkg.mkdir(parents=True)
    # EXPORTED, but under internal/ — still unreachable externally.
    (pkg / "redact.go").write_text(
        "package redact\n\nfunc Mask(s string) string {\n\treturn s\n}\n")
    entry = {"lang": "go", "module": "internal/redact",
             "import": "example.test/fixture/internal/redact",
             "fn": "Mask", "kind": "value"}
    defect, out = _run_one(tmp_path, entry, Probe("p", "test1234", "test1234"))
    assert out == "test1234"
    assert defect and defect.klass in (oracles.LITERAL_SURVIVAL,
                                       oracles.NOOP_PASSTHROUGH)


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
