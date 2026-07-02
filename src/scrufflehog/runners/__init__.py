"""Language runners — each returns a ``produce(probe) -> str`` closure that
yields a redactor's output string. The oracles consume that string and don't
care which language produced it, so adding a language is just adding a producer.

Producers may attach a ``_cleanup`` callable (removes temp build artifacts);
callers should invoke it in a ``finally``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..probes import Probe
from .python_runner import python_producer
from .go_runner import go_producer
from .rust_runner import rust_producer
from .node_runner import node_producer

_PRODUCERS: dict[str, Callable[[Path, dict], Callable[[Probe], str]]] = {
    "python": python_producer,
    "go": go_producer,
    "rust": rust_producer,
    "node": node_producer,
}


def make_producer(target: Path, entry: dict[str, Any]) -> Callable[[Probe], str]:
    lang = entry.get("lang", "python")
    if lang not in _PRODUCERS:
        raise ValueError(f"unknown redactor lang {lang!r}; known: {sorted(_PRODUCERS)}")
    return _PRODUCERS[lang](target, entry)
