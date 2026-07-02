"""Self-contained SARIF 2.1.0 output.

No external dependency: stable rule ids + partial fingerprints are derived here
so the same defect dedups across runs in a SARIF consumer (e.g. GitHub code
scanning). CWE mapping per defect class.
"""
from __future__ import annotations

import hashlib
import json

from ..engine import RunResult
from ..oracles import (COVERAGE_GAP, LITERAL_SURVIVAL, NOOP_PASSTHROUGH,
                       REDACTOR_ERRORED, REVERSIBLE, Defect)

_CWE = {
    LITERAL_SURVIVAL: "CWE-312",   # Cleartext Storage of Sensitive Information
    REVERSIBLE: "CWE-328",         # Use of Weak Hash
    NOOP_PASSTHROUGH: "CWE-311",   # Missing Encryption of Sensitive Data
    COVERAGE_GAP: "CWE-532",       # Insertion of Sensitive Information into Log
    REDACTOR_ERRORED: "CWE-754",   # Improper Check for Unusual Conditions
}
_SECURITY_SEVERITY = "8.0"


def _rule_id(d: Defect) -> str:
    return _CWE.get(d.klass, "CWE-693")


def _fingerprint(d: Defect) -> str:
    composite = f"{_rule_id(d)}|{d.redactor}|{d.klass}|{d.probe}"
    return hashlib.sha256(composite.encode()).hexdigest()


def _module_uri(d: Defect) -> str:
    # redactor label is "module:symbol"; the module part is a repo-relative path.
    return d.redactor.split(":", 1)[0] if ":" in d.redactor else d.redactor


def render_sarif(result: RunResult, target: str) -> str:
    rules: dict[str, dict] = {}
    results = []
    for d in result.defects:
        rid = _rule_id(d)
        if rid not in rules:
            rules[rid] = {
                "id": rid,
                "name": f"scrufflehog/{d.klass}",
                "shortDescription": {"text": f"Ineffective redaction ({d.klass})"},
                "defaultConfiguration": {"level": "error"},
                "properties": {"security-severity": _SECURITY_SEVERITY,
                               "tags": ["security", rid, "scrufflehog"]},
            }
        results.append({
            "ruleId": rid,
            "level": "error",
            "message": {"text": (
                f"{d.klass}: redactor {d.redactor} — {d.detail} (probe: {d.probe})")},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": _module_uri(d)}}}],
            "partialFingerprints": {"primaryLocationLineHash": _fingerprint(d)},
            "properties": {"scrufflehog_class": d.klass,
                           "security-severity": _SECURITY_SEVERITY},
        })
    return json.dumps({
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {
                "name": "scrufflehog",
                "informationUri": "https://github.com/seanturner83/scrufflehog",
                "rules": list(rules.values()),
            }},
            "results": results,
            "properties": {"target": target},
        }],
    }, indent=2)
