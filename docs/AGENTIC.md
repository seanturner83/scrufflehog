# Optional agentic layer — design

## Principle (non-negotiable)

scrufflehog's core is **entirely deterministic** and stays that way. Every
verdict — defect or clean — comes from a hard assertion against known ground
truth (planted probe → run redactor → literal/hash-space/set-membership check).
Same input, same answer, zero false positives, no model. That determinism is the
product's whole thesis: the deterministic counterpart to probabilistic LLM
review.

The agentic layer is **optional, off by default, and never renders a verdict.**
Rule: *the agent proposes INPUTS and HYPOTHESES; the deterministic oracle still
decides.* This preserves the zero-FP guarantee while removing scrufflehog's two
real blind spots (hand-authored probes, unconfirmed coverage hypotheses).

## Where an advisor adds value (three seams)

1. **Probe generation** — read the redactor's signature/body and generate
   probes that match its INPUT DOMAIN. Solves the real footgun (feeding bare
   values to a URL-path redactor → false positives until domain-matched probes
   were hand-written). Generated probes are still run through the deterministic
   oracle; the agent supplies inputs, not verdicts.

2. **Redactor + field discovery** — scan a repo and PROPOSE the registry
   (redaction fns, denylist symbols, sensitive field names). Human/config
   confirms. Discovery, not judgement.

3. **Coverage-gap confirmation** — the honest-caveat killer. A coverage finding
   is a hypothesis ("the list lacks `ssn`" — but does a field named `ssn` reach
   this redactor?). An advisor greps the codebase for real field usage to
   confirm or refute, turning a hypothesis into a confirmed finding or dropping
   it.

## Interface

```python
class Advisor(Protocol):
    def propose_probes(self, redactor_src: str, entry: dict) -> list[Probe]: ...
    def discover_redactors(self, target: Path) -> list[dict]: ...
    def confirm_coverage_gap(self, target: Path, field: str, redactor: str) -> Verdict: ...
```

- `NoopAdvisor` (default): `propose_probes` → [], `discover` → [], `confirm` →
  UNCONFIRMED (finding stands as a hypothesis, exactly today's behaviour).
- `LLMAdvisor` (optional module, extra dependency): implements the three via a
  model. Lives behind `pip install scrufflehog[agentic]`.

CLI:
```
scrufflehog verify --config x.toml --target .                 # pure deterministic
scrufflehog verify --config x.toml --target . --advisor llm   # + agentic assist
```

## Invariants

- A defect is ALWAYS confirmed by the deterministic oracle. The advisor can add
  probes that trigger one, or downgrade a coverage hypothesis to
  confirmed/refuted, but it cannot manufacture a defect the oracle didn't verify.
- With `--advisor` absent, output is byte-identical to today. Reproducibility of
  the deterministic path is a test invariant.
- Advisor failures (timeout, API error) degrade to the deterministic result,
  never crash the run.
