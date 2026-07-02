"""Rust producer — build a driver as an ``examples/`` binary inside the target
crate (so path deps resolve), calling the redactor per stdin line via ``cargo
run --example``.

Config entry fields:
  call : the Rust expression invoking the redactor on `line`,
         e.g. "mycrate::redact::mask(&line)". Must evaluate to something
         Display-able (println!'d).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ..probes import Probe

_DRIVER = '''use std::io::{{BufRead, Write}};
fn main() {{
    let stdin = std::io::stdin();
    let mut out = std::io::stdout();
    for line in stdin.lock().lines() {{
        let line = line.unwrap();
        writeln!(out, "{{}}", {call}).unwrap();
    }}
}}
'''


def rust_producer(target: Path, entry: dict) -> Callable[[Probe], str]:
    if not shutil.which("cargo"):
        raise RuntimeError("cargo toolchain not found on PATH")
    call = entry["call"]
    examples = target / "examples"
    created = not examples.exists()
    examples.mkdir(exist_ok=True)
    drv = examples / "scrufflehog_driver.rs"
    drv.write_text(_DRIVER.format(call=call))

    def _cleanup():
        drv.unlink(missing_ok=True)
        if created:
            try:
                examples.rmdir()
            except OSError:
                pass

    build = subprocess.run(
        ["cargo", "build", "--example", "scrufflehog_driver"],
        cwd=str(target), capture_output=True, text=True)
    if build.returncode != 0:
        _cleanup()
        raise RuntimeError(f"cargo build failed: {build.stderr.strip()[:400]}")

    def produce(p: Probe) -> str:
        val = p.input if isinstance(p.input, str) else str(p.input)
        r = subprocess.run(
            ["cargo", "run", "--quiet", "--example", "scrufflehog_driver"],
            cwd=str(target), input=val + "\n",
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"rust driver exited {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout.rstrip("\n")

    produce._cleanup = _cleanup  # type: ignore[attr-defined]
    return produce
