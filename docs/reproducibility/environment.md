# Environment

## Research runtime

**Python 3.12.** Pinned in `pyproject.toml` (`requires-python = ">=3.12,<3.13"`) and in the container image. The
runtime version is part of the reproducibility metadata, so if the host has a different interpreter, use the
container rather than changing the pin.

## Dependencies

Runtime: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `prometheus-client`, `cryptography`, `PyYAML`.
Development: `pytest`, `pytest-cov`, `httpx`, `ruff`, `mypy`, `types-PyYAML`.

No Redis, PostgreSQL, Celery, Kubernetes or machine-learning library is used. Each would add reproducibility burden
without answering a research question. Whether state or storage components are needed at all will be decided by
measurement in a later batch, not assumed now.

## Metadata capture

`scripts/collect_env.py` records, for every development validation run and later for every experiment run: UTC
timestamp; git commit SHA, dirty status, branch and describe output; Python version and implementation; operating
system, kernel and architecture; CPU model and logical core count; Docker and Compose versions; container image
digest; every installed Python package version; and the configuration hash.

Output goes to `artifacts/dev-validation/`, kept deliberately separate from any future `results/` tree.

## Verified constraints on the development machine (2026-09-06)

- Docker Desktop kernel `7.0.12-linuxkit` has no `/lib/modules`: no loadable kernel modules.
- The available OrbStack machine (`7.0.14-orbstack`) has `cfg80211` but not `mac80211_hwsim`.
- Consequently real 802.11 emulation is not possible on this machine and requires a Linux VM with a stock kernel plus
  `linux-modules-extra`, a GitHub Actions Ubuntu runner, or a cloud VM.

This is why the testbed is two-tier. See ADR-0003.
