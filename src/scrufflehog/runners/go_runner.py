"""Go producer — build a tiny driver that calls the target redactor per stdin
line and prints its output. Built inside the target module so its go.mod + deps
resolve. Compiled once; one stdin line per probe.

Config entry fields:
  import : the Go import path of the package holding the fn
  fn     : the exported function name
  wrap   : "error" → call fn(fmt.Errorf("%s", in)); absent → fn(in) (string param)
"""
from __future__ import annotations

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
