"""Optional advisor interface — the ONLY place non-determinism may enter.

An advisor proposes INPUTS and HYPOTHESES; it never renders a verdict. The
deterministic oracle still decides every defect. The default NoopAdvisor makes
the engine byte-identical to a pure deterministic run — the agentic layer is
strictly additive and opt-in. See docs/AGENTIC.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .probes import Probe


class CoverageVerdict:
    CONFIRMED = "confirmed"      # a real field with this name reaches the redactor
    REFUTED = "refuted"          # no such field is logged here — drop the finding
    UNCONFIRMED = "unconfirmed"  # can't tell — finding stands as a hypothesis


@runtime_checkable
class Advisor(Protocol):
    def propose_probes(self, redactor_src: str, entry: dict) -> list[Probe]: ...
    def discover_redactors(self, target: Path) -> list[dict]: ...
    def confirm_coverage_gap(self, target: Path, field: str, redactor: str) -> str: ...


class NoopAdvisor:
    """Default. Adds nothing; the run stays purely deterministic."""

    def propose_probes(self, redactor_src: str, entry: dict) -> list[Probe]:
        return []

    def discover_redactors(self, target: Path) -> list[dict]:
        return []

    def confirm_coverage_gap(self, target: Path, field: str, redactor: str) -> str:
        return CoverageVerdict.UNCONFIRMED
