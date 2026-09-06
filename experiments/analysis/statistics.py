"""The frozen statistical plan, applied to final results.

Everything here follows ``docs/experiments/final_experiment_protocol.md`` section
10. Nothing chooses a test after seeing an outcome.

Three commitments shape the code:

**The experimental unit is the run.** A run is one (scenario, strategy, seed). The
thousands of decisions inside a run are not independent repetitions of the
experiment, and aggregating them as if they were would inflate every sample size
and manufacture significance. Every function here consumes one value per run.

**The design is paired.** Repetition *i* uses the same seed across the three
strategies, so comparisons are within-seed. Friedman, Wilcoxon and Cochran's Q are
paired tests; Mann-Whitney U is deliberately absent.

**Descriptive first.** Latency and security measurements are skewed, and a sample
of thirty is not a reason to assume otherwise. Median, IQR and p95 with a paired
bootstrap interval are the default presentation; a test is reported alongside
them, never instead of them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from scipy import stats

ALPHA = 0.05
"""Significance level, applied to Holm-adjusted p-values."""

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260906
"""Fixed, so a confidence interval is reproducible rather than merely plausible."""


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile. ``q`` in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * (q / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[int(position)])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def describe(values: list[float]) -> dict[str, Any]:
    """n, median, IQR, p95, min, max. The default presentation."""
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    if not clean:
        return {
            "n": 0,
            "median": None,
            "iqr": None,
            "q1": None,
            "q3": None,
            "p95": None,
            "min": None,
            "max": None,
            "mean": None,
        }
    q1 = percentile(clean, 25)
    q3 = percentile(clean, 75)
    return {
        "n": len(clean),
        "median": round(float(percentile(clean, 50) or 0.0), 6),
        "q1": round(float(q1 or 0.0), 6),
        "q3": round(float(q3 or 0.0), 6),
        "iqr": round(float((q3 or 0.0) - (q1 or 0.0)), 6),
        "p95": round(float(percentile(clean, 95) or 0.0), 6),
        "min": round(min(clean), 6),
        "max": round(max(clean), 6),
        "mean": round(sum(clean) / len(clean), 6),
    }


def normality(values: list[float]) -> dict[str, Any]:
    """Shapiro-Wilk, reported so the reader can see why robust statistics are used.

    It informs presentation; it never selects the test. The protocol fixed a
    rank-based plan in advance precisely so that a normality result cannot be used
    to justify switching to a more convenient test after the fact.
    """
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 3 or len(set(clean)) == 1:
        return {
            "test": "shapiro_wilk",
            "applicable": False,
            "reason": "fewer than 3 distinct values",
        }
    statistic, p_value = stats.shapiro(clean)
    return {
        "test": "shapiro_wilk",
        "applicable": True,
        "statistic": round(float(statistic), 6),
        "p_value": float(p_value),
        "normal_at_0.05": bool(p_value > ALPHA),
    }


# ---------------------------------------------------------------------------
# Paired bootstrap
# ---------------------------------------------------------------------------


def paired_bootstrap_ci(
    a: list[float],
    b: list[float],
    *,
    statistic: str = "median_difference",
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Percentile bootstrap 95% CI for a paired difference (``a - b``).

    Pairs are resampled together, never independently: breaking the pairing would
    discard the very structure the design was built to exploit.
    """
    pairs = [
        (float(x), float(y)) for x, y in zip(a, b, strict=False) if x is not None and y is not None
    ]
    if len(pairs) < 2:
        return {"statistic": statistic, "applicable": False, "n_pairs": len(pairs)}

    def point(sample: list[tuple[float, float]]) -> float:
        diffs = [x - y for x, y in sample]
        if statistic == "mean_difference":
            return sum(diffs) / len(diffs)
        return float(percentile(diffs, 50) or 0.0)

    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    n = len(pairs)
    draws = [point([pairs[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples)]
    return {
        "statistic": statistic,
        "applicable": True,
        "n_pairs": n,
        "point_estimate": round(point(pairs), 6),
        "ci_lower_95": round(float(percentile(draws, 2.5) or 0.0), 6),
        "ci_upper_95": round(float(percentile(draws, 97.5) or 0.0), 6),
        "resamples": resamples,
        "seed": seed,
        "method": "percentile bootstrap over resampled pairs",
    }


# ---------------------------------------------------------------------------
# Multiplicity
# ---------------------------------------------------------------------------


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni step-down adjustment over a family of comparisons."""
    if not p_values:
        return {}
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (key, raw) in enumerate(ordered):
        candidate = min(1.0, (m - index) * raw)
        running = max(running, candidate)  # monotonic, as Holm requires
        adjusted[key] = running
    return adjusted


# ---------------------------------------------------------------------------
# Effect size
# ---------------------------------------------------------------------------


def rank_biserial(a: list[float], b: list[float]) -> dict[str, Any]:
    """Matched-pairs rank-biserial correlation for ``a`` versus ``b``.

    Positive means ``a`` tends to exceed ``b``. Ties contribute nothing, which is
    why the number of non-tied pairs is reported alongside: an effect size over
    two non-tied pairs is not the same evidence as one over thirty.
    """
    pairs = [
        (float(x), float(y)) for x, y in zip(a, b, strict=False) if x is not None and y is not None
    ]
    diffs = [x - y for x, y in pairs]
    non_zero = [d for d in diffs if d != 0]
    if not non_zero:
        return {
            "measure": "matched_pairs_rank_biserial",
            "applicable": False,
            "reason": "every pair is tied",
            "n_pairs": len(pairs),
            "n_non_tied": 0,
        }
    ranks = stats.rankdata([abs(d) for d in non_zero])
    positive = float(sum(r for r, d in zip(ranks, non_zero, strict=True) if d > 0))
    negative = float(sum(r for r, d in zip(ranks, non_zero, strict=True) if d < 0))
    total = positive + negative
    value = (positive - negative) / total if total else 0.0
    magnitude = abs(value)
    interpretation = (
        "negligible"
        if magnitude < 0.1
        else "small"
        if magnitude < 0.3
        else "medium"
        if magnitude < 0.5
        else "large"
    )
    return {
        "measure": "matched_pairs_rank_biserial",
        "applicable": True,
        "value": round(value, 6),
        "n_pairs": len(pairs),
        "n_non_tied": len(non_zero),
        "magnitude": interpretation,
        "direction": (
            "first exceeds second"
            if value > 0
            else "second exceeds first"
            if value < 0
            else "no direction"
        ),
    }


# ---------------------------------------------------------------------------
# Primary comparisons
# ---------------------------------------------------------------------------


@dataclass
class PairedComparison:
    """One metric compared across three paired conditions."""

    metric: str
    scenario: str
    conditions: list[str]
    samples: dict[str, list[float]]
    notes: list[str] = field(default_factory=list)

    def aligned(self) -> tuple[list[str], dict[str, list[float]]]:
        """Truncate to the common length so every comparison stays paired."""
        lengths = {len(self.samples.get(c, [])) for c in self.conditions}
        n = min(lengths) if lengths else 0
        return self.conditions, {c: self.samples.get(c, [])[:n] for c in self.conditions}


def compare_three_paired(comparison: PairedComparison) -> dict[str, Any]:
    """Friedman, then paired Wilcoxon with Holm correction, as the protocol fixes.

    Pairwise tests run only if the omnibus test is significant. Running them
    regardless would be the multiple-comparison problem the omnibus test exists to
    control.
    """
    conditions, samples = comparison.aligned()
    n = len(next(iter(samples.values()), []))
    result: dict[str, Any] = {
        "metric": comparison.metric,
        "scenario": comparison.scenario,
        "conditions": conditions,
        "n_paired_runs": n,
        "experimental_unit": "run (scenario x strategy x seed)",
        "descriptive": {c: describe(samples[c]) for c in conditions},
        "normality": {c: normality(samples[c]) for c in conditions},
        "notes": list(comparison.notes),
    }

    if n < 3:
        result["omnibus"] = {
            "test": "friedman",
            "applicable": False,
            "reason": f"only {n} paired runs",
        }
        return result

    columns = [samples[c] for c in conditions]
    if all(len(set(col)) == 1 for col in columns) and len({col[0] for col in columns}) == 1:
        result["omnibus"] = {
            "test": "friedman",
            "applicable": False,
            "reason": "every condition produced an identical constant value",
        }
        result["interpretation"] = "no difference to test: the conditions agree exactly"
        return result

    statistic, p_value = stats.friedmanchisquare(*columns)
    significant = bool(p_value < ALPHA)
    result["omnibus"] = {
        "test": "friedman",
        "applicable": True,
        "statistic": round(float(statistic), 6),
        "df": len(conditions) - 1,
        "p_value": float(p_value),
        "alpha": ALPHA,
        "significant": significant,
    }

    if not significant:
        result["pairwise"] = {}
        result["interpretation"] = "omnibus not significant; no pairwise comparison is justified"
        return result

    raw_p: dict[str, float] = {}
    pairwise: dict[str, dict[str, Any]] = {}
    for i, first in enumerate(conditions):
        for second in conditions[i + 1 :]:
            key = f"{first}_vs_{second}"
            a, b = samples[first], samples[second]
            if all(x == y for x, y in zip(a, b, strict=True)):
                pairwise[key] = {
                    "test": "wilcoxon_signed_rank",
                    "applicable": False,
                    "reason": "all pairs identical",
                }
                continue
            try:
                w_stat, w_p = stats.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
            except ValueError as exc:
                pairwise[key] = {
                    "test": "wilcoxon_signed_rank",
                    "applicable": False,
                    "reason": str(exc),
                }
                continue
            raw_p[key] = float(w_p)
            pairwise[key] = {
                "test": "wilcoxon_signed_rank",
                "applicable": True,
                "statistic": round(float(w_stat), 6),
                "p_value_raw": float(w_p),
                "effect_size": rank_biserial(a, b),
                "paired_bootstrap_ci": paired_bootstrap_ci(a, b),
            }

    adjusted = holm(raw_p)
    for key, value in adjusted.items():
        pairwise[key]["p_value_holm"] = float(value)
        pairwise[key]["significant_holm"] = bool(value < ALPHA)
    result["pairwise"] = pairwise
    result["correction"] = {"method": "holm_bonferroni", "family_size": len(raw_p)}
    return result


# ---------------------------------------------------------------------------
# Paired binary outcomes
# ---------------------------------------------------------------------------


def cochran_q(conditions: list[str], outcomes: dict[str, list[int]]) -> dict[str, Any]:
    """Cochran's Q over three paired binary conditions, with McNemar follow-up.

    Applied only where the structure genuinely matches: one binary outcome per run
    per condition, the same runs across conditions. Where it does not, the caller
    reports raw counts and paired rates instead of forcing a test onto data that
    does not fit it.
    """
    lengths = {len(outcomes.get(c, [])) for c in conditions}
    n = min(lengths) if lengths else 0
    aligned = {c: outcomes.get(c, [])[:n] for c in conditions}
    result: dict[str, Any] = {
        "test": "cochran_q",
        "conditions": conditions,
        "n_paired_runs": n,
        "successes": {c: int(sum(aligned[c])) for c in conditions},
        "rates": {c: (round(sum(aligned[c]) / n, 6) if n else None) for c in conditions},
    }
    if n < 3:
        result.update(applicable=False, reason=f"only {n} paired runs")
        return result
    if (
        all(len(set(aligned[c])) == 1 for c in conditions)
        and len({aligned[c][0] for c in conditions}) == 1
    ):
        result.update(applicable=False, reason="every condition produced the same constant outcome")
        return result
    try:
        statistic, p_value = stats.cochrans_q(*[aligned[c] for c in conditions])  # type: ignore[attr-defined]
    except AttributeError:
        statistic, p_value = _cochran_q_manual([aligned[c] for c in conditions])
    result.update(
        applicable=True,
        statistic=round(float(statistic), 6),
        df=len(conditions) - 1,
        p_value=float(p_value),
        alpha=ALPHA,
        significant=bool(p_value < ALPHA),
    )
    if not result["significant"]:
        result["pairwise"] = {}
        result["interpretation"] = "omnibus not significant; no pairwise follow-up"
        return result

    raw_p: dict[str, float] = {}
    pairwise: dict[str, dict[str, Any]] = {}
    for i, first in enumerate(conditions):
        for second in conditions[i + 1 :]:
            key = f"{first}_vs_{second}"
            b = sum(1 for x, y in zip(aligned[first], aligned[second], strict=True) if x and not y)
            c = sum(1 for x, y in zip(aligned[first], aligned[second], strict=True) if y and not x)
            if b + c == 0:
                pairwise[key] = {
                    "test": "mcnemar",
                    "applicable": False,
                    "reason": "no discordant pairs",
                    "discordant": 0,
                }
                continue
            table = [[0, b], [c, 0]]
            p = float(stats.binomtest(b, b + c, 0.5).pvalue)
            raw_p[key] = p
            pairwise[key] = {
                "test": "mcnemar_exact",
                "applicable": True,
                "discordant_b": b,
                "discordant_c": c,
                "table": table,
                "p_value_raw": p,
            }
    adjusted = holm(raw_p)
    for key, value in adjusted.items():
        pairwise[key]["p_value_holm"] = float(value)
        pairwise[key]["significant_holm"] = bool(value < ALPHA)
    result["pairwise"] = pairwise
    result["correction"] = {"method": "holm_bonferroni", "family_size": len(raw_p)}
    return result


def _cochran_q_manual(columns: list[list[int]]) -> tuple[float, float]:
    """Cochran's Q from its definition, for SciPy builds without the helper."""
    k = len(columns)
    n = len(columns[0])
    col_totals = [sum(col) for col in columns]
    row_totals = [sum(col[i] for col in columns) for i in range(n)]
    grand = sum(col_totals)
    numerator = (k - 1) * (k * sum(t * t for t in col_totals) - grand * grand)
    denominator = k * grand - sum(r * r for r in row_totals)
    if denominator == 0:
        return 0.0, 1.0
    q = numerator / denominator
    return float(q), float(stats.chi2.sf(q, k - 1))


def confusion_rates(counts: dict[str, int]) -> dict[str, Any]:
    """Rates from raw confusion counts, each carrying its denominator.

    A rate whose denominator is invisible cannot be judged, so every one here is
    returned next to the counts it came from, and a rate with no denominator is
    ``None`` rather than zero.
    """
    tp = int(counts.get("true_positive", counts.get("correct_rejection", 0)))
    tn = int(counts.get("true_negative", counts.get("correct_acceptance", 0)))
    fp = int(counts.get("false_positive", counts.get("false_rejection", 0)))
    fn = int(counts.get("false_negative", counts.get("false_acceptance", 0)))

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    return {
        "counts": {"TP": tp, "TN": tn, "FP": fp, "FN": fn},
        "totals": {
            "illegitimate": tp + fn,
            "legitimate": tn + fp,
            "labelled": tp + tn + fp + fn,
        },
        "false_acceptance_rate": ratio(fn, tp + fn),
        "false_acceptance_denominator": tp + fn,
        "false_rejection_rate": ratio(fp, tn + fp),
        "false_rejection_denominator": tn + fp,
        "detection_rate_recall": ratio(tp, tp + fn),
        "precision": ratio(tp, tp + fp),
        "accuracy": ratio(tp + tn, tp + tn + fp + fn),
        "f1": (round(2 * tp / (2 * tp + fp + fn), 6) if (2 * tp + fp + fn) else None),
        "note": (
            "TP/FN are over adversarial events, TN/FP over legitimate events. "
            "Accuracy alone is not a security conclusion; read it with the counts."
        ),
    }


__all__ = [
    "ALPHA",
    "PairedComparison",
    "cochran_q",
    "compare_three_paired",
    "confusion_rates",
    "describe",
    "holm",
    "normality",
    "paired_bootstrap_ci",
    "percentile",
    "rank_biserial",
]
