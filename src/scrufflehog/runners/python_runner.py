"""Python producer — import the target module in-process and call the redactor.

Supports three call kinds:
  value → fn(str) -> str
  row   → fn(dict) -> dict         (probe wrapped as {"field": value})
  tree  → fn(obj) -> obj           (probe wrapped in a small nested object)
Module is loaded by file path so hyphenated / non-importable filenames work.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

from ..probes import Probe


def _load_callable(target: Path, module_rel: str, fn: str) -> Callable:
    path = target / module_rel
    if not path.exists():
        raise FileNotFoundError(f"module not found: {module_rel}")
    mod_name = "scrufflehog_target_" + (
        module_rel.replace("/", "_").replace(".", "_").replace("-", "_"))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {module_rel}")
    mod = importlib.util.module_from_spec(spec)
    # Sibling imports relative to the module's dir.
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        if str(path.parent) in sys.path:
            sys.path.remove(str(path.parent))
    if not hasattr(mod, fn):
        raise AttributeError(f"{module_rel} has no attribute {fn!r}")
    return getattr(mod, fn)


def _apply(fn: Callable, kind: str, probe: Probe) -> str:
    if kind == "value":
        v = probe.input if isinstance(probe.input, str) else str(probe.input)
        return str(fn(v))
    if kind == "row":
        return json.dumps(fn({"field": probe.input}), default=str)
    if kind == "tree":
        obj: dict[str, Any] = {"data": {"field": probe.input}}
        out = fn(obj)
        return json.dumps(out if out is not None else obj, default=str)
    raise ValueError(f"unknown call kind: {kind}")


def python_producer(target: Path, entry: dict) -> Callable[[Probe], str]:
    fn = _load_callable(target, entry["module"], entry["fn"])
    kind = entry.get("kind", "value")
    return lambda p: _apply(fn, kind, p)
