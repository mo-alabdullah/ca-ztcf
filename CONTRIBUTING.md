# Contributing

This repository is the software artefact of a master's thesis. It is developed in the open so that
the experiments can be reproduced and archived, but the research direction is set by the thesis.

## Development setup

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
make check
```

If Python 3.12 is not available on the host, use the container instead
(`make docker-build`). Do not silently change the research runtime to a different
Python version: the runtime is part of the reproducibility metadata.

## Quality gates

Every change must pass `make check` (ruff, mypy, pytest). Tests must not use `sleep`;
use `FrozenClock` from `ca_ztcf.clock` to control time.

## Rules specific to this project

1. **No research threshold in Python.** Every threshold, TTL, window, limit and allow-list lives in
   `config/`, with a name, unit, purpose and default. Magic constants are rejected in review.
2. **No performance or security claims.** Until the experiments are run and analysed, write
   "designed to", "intended to", "will be evaluated for". Never "reduces latency", "improves
   security", "is lightweight" or "scales better".
3. **No cross-domain identifier comparison.** 5G and WiFi identifiers are access evidence only.
   They are hashed inside their own collector and must never be compared with one another.
4. **No secrets.** Generated credentials go to `secrets/`, which is git-ignored. Run
   `make secret-scan` before committing.
5. **No fabricated DOI.** `CITATION.cff` gains a `doi:` field only after Zenodo issues one.
6. **Synthetic data is labelled.** Development fixtures carry `source_mode: synthetic_fixture`
   and are never presented as measured results.
