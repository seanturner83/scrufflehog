"""scrufflehog — deterministically verify that your redactors actually redact.

Everyone scans for secrets that leaked. scrufflehog tests whether the redaction
you rely on actually works: it runs adversarial probes through your own redactor
and asserts the secret is gone and not trivially reversible, and checks your
field denylist/allow-list covers the sensitive names you think it does.
"""
from .oracles import Defect, assert_output, reversible
from .probes import Probe, get_probe_set
from .engine import RunResult, run

__version__ = "0.1.1"
__all__ = ["Defect", "assert_output", "reversible", "Probe", "get_probe_set",
           "RunResult", "run"]
