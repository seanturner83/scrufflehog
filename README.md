# scrufflehog

**Unit-test your redaction.**

Everyone scans for secrets that already leaked (trufflehog, gitleaks). Almost
nobody tests whether the redaction they *rely on* actually works. scrufflehog is
the inverse tool: it runs adversarial probes through your own redaction code and
deterministically asserts the secret is gone — and checks that your field
denylist/allow-list covers the sensitive names you think it does.

No model, no guessing: every verdict is a hard assertion against a planted secret
you control. Zero false positives by construction.

## Two things it checks

**1. Transform-strength** — *does the redactor's output still contain, or
trivially reverse to, the secret?* It executes your redactor on planted probes
and applies three oracles:

- `literal_survival` — the secret appears verbatim in the output.
- `noop_passthrough` — the "redactor" returned its input unchanged.
- `reversible` — the output is a keyless, low-entropy transform (truncated or
  unsalted hash, base64, static substitution) that a bounded candidate space
  recovers. Catches "redaction" that only *looks* redacted.

**2. Coverage** — *is every sensitive field name actually on your list?* A field
denylist/allow-list is data, not behaviour, so scrufflehog extracts it straight
from source and checks a sensitive-field corpus against it — **without executing
your code**. This works across languages (Go maps, Python collections,
pino/`fast-redact` path lists, Rust sets).

## Languages

| | transform-strength | coverage |
|---|---|---|
| Python | in-process import | ✓ |
| Go | driver built in your module | ✓ (map literals) |
| Rust | `cargo --example` driver | ✓ (set literals) |
| Node/JS | node driver via stdin | ✓ (pino path lists) |

## Install

Latest from source (works today):

```bash
pip install git+https://github.com/seanturner83/scrufflehog
```

Once the first release is published, from PyPI:

```bash
pip install scrufflehog
```

## Use

Write a `scrufflehog.toml` declaring your redactors (see `examples/`):

```toml
[[transform]]
lang = "python"
module = "app/redact.py"
fn = "redact_value"
kind = "value"

[[coverage]]
module = "app/redact.py"
symbol = "SECRET_FIELDS"
extract = "py_collection"
match = "exact_ci"
```

Then:

```bash
scrufflehog verify --config scrufflehog.toml --target . --format text
scrufflehog verify --config scrufflehog.toml --target . --format sarif   # for code-scanning
scrufflehog verify --config scrufflehog.toml --target . --fail-on-defect # CI gate
```

## Deterministic by default; optional agentic assist

The core is entirely deterministic and that's the point. An **optional** advisor
(`--advisor llm`) can propose domain-matched probes, discover redactors, and
confirm coverage hypotheses against real field usage — but it only ever supplies
*inputs and hypotheses*; the deterministic oracle still renders every verdict.
With no advisor, output is fully reproducible. See `docs/AGENTIC.md`.

### Bring your own model

scrufflehog ships no LLM SDK and talks to no provider by default — you point it
at *your* model. Set `SCRUFFLEHOG_LLM` to a `module:function` path resolving to a
`complete(prompt: str) -> str` callable, put it on `PYTHONPATH`, and pass
`--advisor llm`:

```python
# my_backend.py  (anywhere on your PYTHONPATH)
import anthropic
_client = anthropic.Anthropic()

def complete(prompt: str) -> str:
    msg = _client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")
```

```bash
export SCRUFFLEHOG_LLM="my_backend:complete"
export PYTHONPATH="$(dirname my_backend.py):$PYTHONPATH"
scrufflehog verify --config scrufflehog.toml --target . --advisor llm
```

Any backend works — OpenAI, Bedrock, Ollama, a local model — as long as it
exposes `complete(prompt) -> str`. The advisor degrades to the deterministic
result on any backend error, so a flaky model never fails or corrupts a run.

To let the advisor supply the probe set for a redactor whose input domain the
generic probes miss (e.g. a URL-scoped redactor), set `probe_set = "advisor"` on
that transform entry; it falls back to the built-in `value` set when no advisor
is present.

## Why "scrufflehog"

trufflehog finds the secrets. scrufflehog scruffs through the code that's
*supposed to hide them* and checks it actually does.

## License

MIT.
