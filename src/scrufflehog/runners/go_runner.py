"""Go producer — build a tiny driver that calls the target redactor per stdin
line and prints its output. Built inside the target module so its go.mod + deps
resolve. Compiled once; one stdin line per probe.

Config entry fields:
  import : the Go import path of the package holding the fn
  fn     : the function name — exported OR package-private (see below)
  wrap   : "error" → call fn(fmt.Errorf("%s", in)); absent → fn(in) (string param)

UNEXPORTED FUNCTIONS. Idiomatic Go keeps redaction helpers package-private, so a
driver in its own `package main` cannot see them. Measured on a real fleet, 11 of
12 redactors were unexported and every one failed with `undefined: pkg.fn` — the
runner was blind to ~92% of the population it was pointed at.

So there are two strategies, tried in order:
  1. external driver — `package main` importing the target package. Fast, and the
     only option when the target is a compiled binary's package.
  2. IN-PACKAGE driver — a `_test.go` file written into the target package itself,
     run via `go test -run`. Test files compile as part of the package, so they can
     call package-private identifiers.
Strategy 2 has two constraints that shape its design: `go test` does NOT forward
stdin, so probes are baked into the generated source as a table; and the driver
lands in the CALLER'S SOURCE TREE, so it is removed in a finally and named
`zz_scrufflehog_driver_test.go` to be obvious and sort last if anything leaks.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ..probes import Probe

_DRIVER = '''package main
import (
\t"bufio"
\t"fmt"
\t"os"
\t"{imp}"
)
func main() {{
\tsc := bufio.NewScanner(os.Stdin)
\tsc.Buffer(make([]byte, 1024*1024), 1024*1024)
\tfor sc.Scan() {{
\t\tin := sc.Text()
\t\tfmt.Println({call})
\t}}
}}
'''


_INPKG_DRIVER = '''package {pkg}

import (
	"fmt"
	"os"
	"testing"
)

func TestZZScrufflehogDriver(t *testing.T) {{
	if os.Getenv("SCRUFFLEHOG_DRIVER") == "" {{
		t.Skip("scrufflehog probe driver")
	}}
	for _, in := range []string{{
		{literals},
	}} {{
		fmt.Println("SCRUFFLEHOG_OUT:" + fmt.Sprint({call}))
	}}
}}
'''

_INPKG_FILE = "zz_scrufflehog_driver_test.go"
_OUT_MARK = "SCRUFFLEHOG_OUT:"


def _go_quote(s: str) -> str:
    """Go interpreted-string literal. Probes contain quotes, backslashes and %."""
    return '"' + (s.replace("\\", "\\\\")
                   .replace('"', '\\"')
                   .replace("\n", "\\n")
                   .replace("\r", "\\r")
                   .replace("\t", "\\t")) + '"'


def _inpkg_source(pkg: str, fn: str, wrap: str | None,
                  inputs: list[str]) -> str:
    call = f'{fn}(fmt.Errorf("%s", in))' if wrap == "error" else f"{fn}(in)"
    literals = ",\n\t\t".join(_go_quote(i) for i in inputs)
    return _INPKG_DRIVER.format(pkg=pkg, call=call, literals=literals)


def _driver_source(imp: str, fn: str, wrap: str | None) -> str:
    pkg = imp.rsplit("/", 1)[-1]
    if wrap == "error":
        call = f'{pkg}.{fn}(fmt.Errorf("%s", in))'
    else:
        call = f'{pkg}.{fn}(in)'
    return _DRIVER.format(imp=imp, call=call)


def go_producer(target: Path, entry: dict) -> Callable[[Probe], str]:
    if not shutil.which("go"):
        raise RuntimeError("go toolchain not found on PATH")
    src = _driver_source(entry["import"], entry["fn"], entry.get("wrap"))

    workdir = target / ".scrufflehog_driver"
    workdir.mkdir(exist_ok=True)
    (workdir / "main.go").write_text(src)
    bin_path = workdir / "driver"
    build = subprocess.run(
        ["go", "build", "-o", str(bin_path), str(workdir / "main.go")],
        cwd=str(target), capture_output=True, text=True)
    if build.returncode != 0:
        shutil.rmtree(workdir, ignore_errors=True)
        # Two distinct reasons an external driver cannot reach a real target, both
        # measured against a live fleet:
        #   * "undefined: pkg.fn"  — the function is package-private (11 of 12
        #     redactors in that fleet).
        #   * "use of internal package ... not allowed" — Go's internal/ visibility
        #     rule blocks the import ENTIRELY, however the function is spelled. Any
        #     redactor under internal/ is unreachable this way, exported or not.
        # Both are answered by the in-package driver, so fall back rather than
        # reporting redactor_errored — see the module docstring.
        if ("undefined:" in build.stderr
                or "internal package" in build.stderr):
            return _inpkg_producer(target, entry)
        raise RuntimeError(f"go build failed: {build.stderr.strip()[:400]}")

    def produce(p: Probe) -> str:
        val = p.input if isinstance(p.input, str) else str(p.input)
        r = subprocess.run([str(bin_path)], input=val + "\n",
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"driver exited {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout.rstrip("\n")

    produce._cleanup = lambda: shutil.rmtree(workdir, ignore_errors=True)  # type: ignore[attr-defined]
    return produce


def _inpkg_producer(target: Path, entry: dict) -> Callable[[Probe], str]:
    """Call a PACKAGE-PRIVATE redactor via a generated in-package test driver.

    `go test` does not forward stdin, so the probe inputs must be compiled in. The
    caller hands us one Probe at a time, so the driver is regenerated and run per
    probe — a `go test` invocation is ~1-3s against a warm build cache, which is
    the price of reaching the 92% of real redactors an external driver cannot see.
    """
    pkg_dir = _package_dir(target, entry)
    if pkg_dir is None:
        raise RuntimeError(
            f"cannot locate the package directory for {entry['import']!r} — "
            "needed to reach an unexported function")
    pkg_name = _package_name(pkg_dir)
    if not pkg_name:
        raise RuntimeError(f"could not resolve the package name in {pkg_dir}")
    fn = entry["fn"]
    wrap = entry.get("wrap")

    def produce(p: Probe) -> str:
        val = p.input if isinstance(p.input, str) else str(p.input)
        drv = pkg_dir / _INPKG_FILE
        try:
            drv.write_text(_inpkg_source(pkg_name, fn, wrap, [val]))
            r = subprocess.run(
                ["go", "test", "-run", "TestZZScrufflehogDriver", "-v",
                 "-count=1", "."],
                cwd=str(pkg_dir), capture_output=True, text=True, timeout=300,
                env={**os.environ, "SCRUFFLEHOG_DRIVER": "1"},
            )
        finally:
            with contextlib.suppress(OSError):
                drv.unlink()
        outs = [ln.split(_OUT_MARK, 1)[1].rstrip()
                for ln in r.stdout.splitlines() if _OUT_MARK in ln]
        if not outs:
            tail = (r.stdout + r.stderr).strip()[-300:]
            raise RuntimeError(f"in-package driver produced no output: {tail}")
        return outs[0]

    # Nothing persistent to clean: each call removes its own driver in a finally.
    produce._cleanup = lambda: None  # type: ignore[attr-defined]
    return produce


def _package_dir(target: Path, entry: dict) -> Path | None:
    """Directory holding the target package. Prefers an explicit `dir`, then the
    import path's tail relative to the module root, then a `module` hint."""
    if entry.get("dir"):
        cand = target / entry["dir"]
        return cand if cand.is_dir() else None
    mod_root = _module_path(target)
    imp = entry.get("import", "")
    if mod_root and imp.startswith(mod_root):
        rel = imp[len(mod_root):].lstrip("/")
        cand = target / rel if rel else target
        if cand.is_dir():
            return cand
    if entry.get("module"):
        cand = target / entry["module"]
        if cand.is_dir():
            return cand
        if cand.suffix == ".go" and cand.parent.is_dir():
            return cand.parent
    return None


def _module_path(target: Path) -> str:
    """The `module` line from go.mod, or "" when absent."""
    gomod = target / "go.mod"
    if not gomod.is_file():
        return ""
    for line in gomod.read_text(errors="replace").splitlines():
        if line.startswith("module "):
            return line.split(None, 1)[1].strip()
    return ""


def _package_name(pkg_dir: Path) -> str:
    """The Go package name declared in a directory, via `go list`."""
    try:
        r = subprocess.run(["go", "list", "-f", "{{.Name}}", "."],
                           cwd=str(pkg_dir), capture_output=True, text=True,
                           timeout=120)
    except (subprocess.SubprocessError, OSError):
        return ""
    return r.stdout.strip()
