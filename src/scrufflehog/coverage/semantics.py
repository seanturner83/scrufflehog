"""Match semantics — how a redactor decides whether a field name is covered.

Mirrors the target redactor's own matching so the coverage verdict reflects what
the redactor actually does, not what we assume.
"""
from __future__ import annotations


def covered(field_name: str, keys: set[str], match: str) -> bool:
    f = field_name.lower()
    if match == "exact_ci":
        return f in keys
    if match == "substring_ci":
        # redactor redacts a field if ANY key is a substring of the field name
        return any(k in f for k in keys)
    if match == "field_substring_ci":
        # inverse: redactor redacts if the field name is a substring of any key
        return any(f in k for k in keys)
    raise ValueError(f"unknown match semantics: {match!r}")
