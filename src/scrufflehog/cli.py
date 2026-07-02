"""scrufflehog CLI — verify a target's redactors against a config."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .engine import run
from .output import FORMATTERS


def _load_advisor(name: str):
    if name == "none":
        from .advisor import NoopAdvisor
        return NoopAdvisor()
    if name == "llm":
        from .advisors.llm import LLMAdvisor
        complete = _resolve_completion_backend()
        if complete is None:
            print("--advisor llm needs a completion backend. Set SCRUFFLEHOG_LLM "
                  "to a 'module:function' path resolving to a complete(prompt)->str "
                  "callable (e.g. your Anthropic/OpenAI/Bedrock wrapper).",
                  file=sys.stderr)
            raise SystemExit(2)
        return LLMAdvisor(complete)
    raise SystemExit(f"unknown advisor: {name!r}")


def _resolve_completion_backend():
    """Resolve a `complete(prompt)->str` callable from SCRUFFLEHOG_LLM=
    'package.module:function'. Provider-agnostic — the user points it at their
    own model wrapper, so scrufflehog needs no SDK dependency."""
    import importlib
    import os
    spec = os.environ.get("SCRUFFLEHOG_LLM")
    if not spec or ":" not in spec:
        return None
    mod_name, fn_name = spec.split(":", 1)
    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, fn_name)
    except (ImportError, AttributeError) as e:
        print(f"could not load SCRUFFLEHOG_LLM={spec!r}: {e}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scrufflehog",
        description="Deterministically verify that your redactors actually redact.")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify redactors declared in a config")
    v.add_argument("--config", required=True, type=Path)
    v.add_argument("--target", required=True, type=Path,
                   help="repo checkout the config's module paths are relative to")
    v.add_argument("--format", choices=sorted(FORMATTERS), default="text")
    v.add_argument("--advisor", choices=["none", "llm"], default="none",
                   help="optional agentic assist (proposes probes / confirms "
                        "coverage gaps); verdicts stay deterministic")
    v.add_argument("--fail-on-defect", action="store_true",
                   help="exit non-zero if any defect is found (for CI gating)")

    args = p.parse_args(argv)

    if args.cmd == "verify":
        if not args.target.is_dir():
            print(f"target not a directory: {args.target}", file=sys.stderr)
            return 2
        config = load_config(args.config)
        advisor = _load_advisor(args.advisor)
        result = run(args.target, config, advisor)
        print(FORMATTERS[args.format](result, str(args.target)))
        if args.fail_on_defect and result.defects:
            return 1
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
