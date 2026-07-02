"""Node producer — run a small JS driver that requires the target module and
calls the redactor per stdin line. Runs from the target dir so its node_modules
resolves. Supports CommonJS require of a module path + a named export.

Config entry fields:
  module : path (relative to target) to require, e.g. "dist/redact.js"
  fn     : exported function name; called as mod[fn](line)
  export : optional — if the module's export IS the fn (module.exports = fn),
           set export="default" and fn is ignored.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ..probes import Probe

_DRIVER = '''const path = require('path');
const mod = require(path.resolve(process.argv[2]));
const fn = {resolve_fn};
let buf = '';
process.stdin.on('data', d => buf += d);
process.stdin.on('end', () => {{
  buf.split('\\n').filter(l => l.length).forEach(line => {{
    const out = fn(line);
    console.log(typeof out === 'string' ? out : JSON.stringify(out));
  }});
}});
'''


def node_producer(target: Path, entry: dict) -> Callable[[Probe], str]:
    if not shutil.which("node"):
        raise RuntimeError("node runtime not found on PATH")
    module_rel = entry["module"]
    if not (target / module_rel).exists():
        raise FileNotFoundError(f"node module not found: {module_rel}")
    if entry.get("export") == "default":
        resolve_fn = "mod"
    else:
        fn = entry["fn"]
        resolve_fn = f"mod[{fn!r}] || (mod.default && mod.default[{fn!r}])"
    driver_src = _DRIVER.format(resolve_fn=resolve_fn)

    workdir = target / ".scrufflehog_driver"
    workdir.mkdir(exist_ok=True)
    drv = workdir / "driver.js"
    drv.write_text(driver_src)
    abs_module = str((target / module_rel).resolve())

    def produce(p: Probe) -> str:
        val = p.input if isinstance(p.input, str) else str(p.input)
        r = subprocess.run(
            ["node", str(drv), abs_module],
            cwd=str(target), input=val + "\n",
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"node driver exited {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout.rstrip("\n")

    produce._cleanup = lambda: shutil.rmtree(workdir, ignore_errors=True)  # type: ignore[attr-defined]
    return produce
