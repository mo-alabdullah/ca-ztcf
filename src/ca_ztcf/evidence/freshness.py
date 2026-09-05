"""Freshness helpers.

Freshness is expressed once, here, so that every predicate applies the same rule
and a test can reason about boundary values without duplicating arithmetic.

The boundary is inclusive: an observation exactly ``ttl`` seconds old is still
fresh. This is stated explicitly because boundary behaviour is a controlled
variable in the experimental programme.
"""

from __future__ import annotations

from datetime import datetime

from ca_ztcf.evidence.models import ValidationStatus


def age_seconds(observed_at: datetime, now: datetime) -> float:
    """Age of an observation in seconds; never negative."""
    return max(0.0, (now - observed_at).total_seconds())


def is_fresh(observed_at: datetime, now: datetime, ttl_s: float) -> bool:
    """Whether an observation is within ``ttl_s`` seconds of ``now`` (inclusive)."""
    if ttl_s < 0:
        raise ValueError("ttl_s must not be negative")
    return age_seconds(observed_at, now) <= ttl_s


def freshness_status(
    observed_at: datetime | None,
    now: datetime,
    ttl_s: float,
) -> ValidationStatus:
    """Classify an observation as VALID, STALE or MISSING."""
    if observed_at is None:
        return ValidationStatus.MISSING
    return ValidationStatus.VALID if is_fresh(observed_at, now, ttl_s) else ValidationStatus.STALE


__all__ = ["age_seconds", "freshness_status", "is_fresh"]
