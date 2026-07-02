"""Static extraction of a redactor's field-name denylist / allow-list.

A field-name list is DATA, not behaviour — so we can extract it from source and
check coverage WITHOUT executing the target's language. This is what makes
coverage mode language-agnostic.

Extractors:
  go_map_keys     — keys of `var X = map[string]struct{}{ "k": {}, ... }`
  py_collection   — string entries of a Python list/tuple/set literal
  ts_redact_paths — leaf field names from a path allow-list
                    (e.g. redact.req('body.email') -> email;
                     body.message[*].phone_number -> phone_number)
  rust_str_set    — string literals in a Rust slice/array/HashSet-from literal

Fails LOUD on an empty extraction: an empty set from source that plainly has
entries means the extractor missed the literal, and silently returning it would
false-positive "everything is missed" on a good list. A genuinely empty list is
reportable, but must be proven, not inferred from a parse miss.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# A generic, public-knowledge corpus of field names a PII/secret redactor is
# reasonably expected to cover. Users can override per-target in config.
DEFAULT_SENSITIVE_FIELDS = [
    "ssn", "social_security_number", "cvv", "cvc", "card_number", "pan",
    "iban", "swift", "routing_number", "account_number", "phone_number",
    "phone", "mobile", "passport", "passport_number", "drivers_license",
    "dob", "date_of_birth", "email", "email_address", "password", "secret",
    "token", "api_key", "apikey", "authorization", "pin", "security_code",
    "credit_card", "bank_account", "tax_id",
]

_GO_MAP_KEY_RE = re.compile(r'"([^"\\]+)"\s*:\s*\{\}')
_STR_RE = re.compile(r'"([^"\\]+)"|\'([^\'\\]+)\'')


def _scoped_block(src: str, symbol: str, extract: str) -> str:
    """Return the literal block belonging to `symbol`, brace/bracket-balanced.
    Anchors on a declaration (`symbol =` / `symbol:` / map decl), not a comment
    mention. Handles Go's `map[string]struct{}{` (first `{` is struct{}'s body)."""
    m = re.search(rf'\b{re.escape(symbol)}\b\s*(?:=|:?=|:|\bmap\b|\[\])', src)
    idx = m.start() if m else src.find(symbol)
    if idx == -1:
        raise ValueError(f"symbol {symbol!r} not found")

    if extract == "go_map_keys":
        open_re = re.search(r'\}\s*\{', src[idx:])
        if not open_re:
            raise ValueError(f"could not locate map literal opening for {symbol!r}")
        brace = idx + open_re.end() - 1
    else:
        candidates = [p for p in (src.find("{", idx), src.find("[", idx),
                                   src.find("(", idx)) if p != -1]
        if not candidates:
            raise ValueError(f"no literal block after {symbol!r}")
        brace = min(candidates)

    opener = src[brace]
    closer = {"{": "}", "[": "]", "(": ")"}[opener]
    depth, end = 0, brace
    for i in range(brace, len(src)):
        if src[i] == opener:
            depth += 1
        elif src[i] == closer:
            depth -= 1
            if depth == 0:
                end = i
                break
    return src[brace:end + 1]


def extract_key_set(target: Path, spec: dict[str, Any]) -> set[str]:
    path = target / spec["module"]
    if not path.exists():
        raise FileNotFoundError(f"coverage module not found: {spec['module']}")
    src = path.read_text(encoding="utf-8", errors="replace")
    extract = spec["extract"]
    block = _scoped_block(src, spec["symbol"], extract)

    if extract == "go_map_keys":
        keys = {m.lower() for m in _GO_MAP_KEY_RE.findall(block)}
    elif extract in ("py_collection", "rust_str_set"):
        keys = {(a or b).lower() for a, b in _STR_RE.findall(block)}
    elif extract == "ts_redact_paths":
        keys = set()
        for a, b in _STR_RE.findall(block):
            raw = a or b
            leaf = re.sub(r'\[[^\]]*\]', '', raw).rstrip('.').split('.')[-1]
            leaf = leaf.strip().strip('"\'')
            if leaf:
                keys.add(leaf.lower())
    else:
        raise ValueError(f"unknown extract kind: {extract!r}")

    if not keys:
        raise ValueError(
            f"extracted 0 keys from {spec['symbol']!r} in {spec['module']} — "
            f"the extractor likely failed to locate the literal (fail-loud: "
            f"refusing to report a false 'everything missed').")
    return keys
