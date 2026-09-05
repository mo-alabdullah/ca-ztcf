# How to reproduce this milestone

Everything below has been run; the commands are the exact ones used.

## 1. Quality gates on the host

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
make check
```

`make check` runs, in order: `ruff check` and `ruff format --check`; `mypy`; `pytest`.

For coverage:

```bash
make test-cov
```

## 2. Secret scan

```bash
make secret-scan
```

Heuristic scan over tracked and untracked-but-not-ignored content, for private key blocks, cloud credentials, tokens
and credential assignments. It is a gate, not a substitute for a dedicated scanner.

## 3. Container

```bash
make docker-build
make docker-up
```

The service listens on `http://127.0.0.1:8080`. It runs as a non-root user, read-only, with all capabilities dropped
and `no-new-privileges` set. Configuration is mounted read-only, so the running service cannot alter the
configuration its output is attributed to.

## 4. Endpoint checks

```bash
curl -s localhost:8080/healthz
curl -s localhost:8080/readyz
curl -s localhost:8080/version
curl -s localhost:8080/config/hash
curl -s localhost:8080/metrics | head
```

## 5. Development validation flow

```bash
make smoke
```

Drives the full sequence: enrol a device; steady 5G session (STABLE / ALLOW); 5G → WiFi transition (TRANSITIONAL /
ALLOW_WITH_RESTRICTIONS); evidence settles (STABLE / ALLOW); identity mismatch (UNTRUSTED / DENY); unregistered device
(UNKNOWN / DENY / REGISTRATION_REQUIRED).

**This is a functional check, not an experiment.** All access-domain events it submits are development fixtures
carrying `source_mode: synthetic_fixture`. Its report is written to `artifacts/dev-validation/`, deliberately separate
from any future `results/` tree, and carries that disclaimer.

## 6. Environment metadata

```bash
make env
```

## 7. Research key material

```bash
./scripts/gen_certs.sh
```

Writes Ed25519 key pairs to `secrets/`, which is git-ignored. Nothing there is a production credential; regenerate
freely and never commit it.
