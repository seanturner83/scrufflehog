"""Load a scrufflehog config — the externalised redactor registry.

TOML shape (see examples/):

    [[transform]]
    lang = "python"          # python | go | rust | node
    module = "app/redact.py"
    fn = "redact"
    kind = "value"           # value | row | tree
    probe_set = "value"      # value | url_apikey
    # go extras:  import = "...", wrap = "error"
    # rust extras: call = "mycrate::redact(&line)"
    # node extras: export = "default"

    [[coverage]]
    module = "app/redact.py"
    symbol = "SECRET_KEYS"
    extract = "py_collection"   # go_map_keys | py_collection | ts_redact_paths | rust_str_set
    match = "exact_ci"          # exact_ci | substring_ci | field_substring_ci
    doc_claims_substring = false
    # corpus = ["ssn", "cvv", ...]   # optional; defaults to the built-in list
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    config = {"transform": data.get("transform", []),
              "coverage": data.get("coverage", [])}
    _validate(config)
    return config


def _validate(config: dict[str, Any]) -> None:
    for e in config["transform"]:
        for req in ("lang", "module"):
            if req not in e:
                raise ValueError(f"transform entry missing {req!r}: {e}")
        if e["lang"] != "rust" and "fn" not in e and e.get("export") != "default":
            raise ValueError(f"transform entry needs 'fn' (or export='default'): {e}")
    for s in config["coverage"]:
        for req in ("module", "symbol", "extract"):
            if req not in s:
                raise ValueError(f"coverage entry missing {req!r}: {s}")
