"""Synthetic probes — planted sensitive inputs fed through a redactor.

A probe carries a known secret (ground truth), so "was it suppressed?" is a hard
assertion rather than a judgement. `secret_space`, when set, bounds the
reversibility oracle: it models "an attacker knows this value is one of these N
candidates" (weak passphrases, enum values, known config) and is the ONLY thing
the oracle is allowed to enumerate — so we never claim a high-entropy value is
reversible.

Probes must match the redactor's INPUT DOMAIN. A redactor that only touches URL
paths must get URL-shaped probes; feeding it a bare value tests nothing and
manufactures false positives. Pick a probe set per redactor accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Probe:
    name: str
    input: Any                        # what the redactor is called with
    secret: str                       # the value that must be suppressed
    secret_space: list[str] = field(default_factory=list)
    sensitive: bool = True            # is the INPUT itself sensitive? (no-op check)


def weak_secret_space() -> list[str]:
    """A deliberately tiny candidate space for the reversibility oracle — common
    weak/guessable values. Not a real cracking dictionary; the point is
    'recoverable from a plausible small space', not brute force."""
    return [
        "test1234", "password", "changeme", "admin", "letmein",
        "s3cr3t", "hunter2", "postgres", "root", "secret",
    ]


def value_probes() -> list[Probe]:
    """Generic value-domain probes — for a redactor that claims to redact ANY
    sensitive VALUE. A narrower-domain redactor should use a matching set."""
    weak = "test1234"
    return [
        Probe("weak-passphrase", weak, weak, secret_space=weak_secret_space()),
        Probe("db-url-cred",
              "postgres://svc:test1234@db.example.internal:5432/core",
              "test1234", secret_space=weak_secret_space()),
        Probe("high-entropy-key",
              "AKIAEXAMPLE0000/wJalrXUtnFEMIK7MDENGEXAMPLEKEY0000",
              "wJalrXUtnFEMIK7MDENGEXAMPLEKEY0000"),  # no space → not claimed reversible
    ]


def url_apikey_probes() -> list[Probe]:
    """Probes for a URL-path API-key redactor. The secret is embedded in a URL
    path segment — the redactor's actual input domain."""
    key = "abcdef0123456789abcdef0123456789"
    return [
        Probe("rpc-url-apikey",
              f"failed to dial https://provider.example.com/v2/{key}: timeout",
              key),
        Probe("api-url-apikey",
              f"error: https://api.example.com/v3/{key} returned 401",
              key),
    ]


# Named probe sets a config entry can opt into by name.
PROBE_SETS: dict[str, Callable[[], list[Probe]]] = {
    "value": value_probes,
    "url_apikey": url_apikey_probes,
}


def get_probe_set(name: str) -> list[Probe]:
    if name not in PROBE_SETS:
        raise ValueError(
            f"unknown probe_set {name!r}; known: {sorted(PROBE_SETS)}")
    return PROBE_SETS[name]()
