"""Grain and key candidate analysis (spec §9.2).

A proposed key must have: no null components, and uniqueness verified over the
COMPLETE committed candidate dataset — not a sample. Combination count and
width are capped. Business meaning is confirmed by a human, never inferred.
"""

from __future__ import annotations

from itertools import combinations

import polars as pl

from .config import LIMITS


def grain_candidates(frame: pl.DataFrame) -> list[dict]:
    out: list[dict] = []
    cols = frame.columns
    singletons = [c for c in cols if c.lower().endswith("_id") or c.lower() in ("id", "code")] or cols
    combos: list[tuple[str, ...]] = [(c,) for c in singletons]
    if len(combos) < LIMITS.max_key_candidates:
        combos += list(combinations(cols, 2))
    combos = combos[: LIMITS.max_key_candidates]

    for key in combos:
        nulls = int(sum(frame[k].is_null().sum() for k in key))
        empty = 0
        for k in key:
            if frame[k].dtype == pl.Utf8:
                empty += frame[k].is_in(["", None]).sum()
        dup_mask = frame.group_by(list(key)).len()
        dupes = dup_mask.filter(pl.col("len") > 1)
        n_dup_groups = dupes.height
        unique_full = (nulls + empty) == 0 and n_dup_groups == 0 and (dup_mask["len"].max() or 0) <= 1
        examples = []
        if n_dup_groups:
            worst = dup_mask.filter(pl.col("len") > 1).sort("len", descending=True).head(3)
            for row in worst.to_dicts():
                ex = {k: row[k] for k in key}
                ex["occurrences"] = row["len"]
                examples.append(ex)
        out.append({
            "key_columns": list(key),
            "unique_over_full_data": bool(unique_full),
            "null_components": int(nulls + empty),
            "duplicate_examples": examples,
            "business_meaning": "unconfirmed",
        })
    return out


def relationship_profile(left: pl.DataFrame, right: pl.DataFrame, on: str) -> dict:
    """Cardinality + unmatched rate for a candidate join path (§9.2)."""
    left_keys = set(left[on].drop_nulls().to_list())
    right_keys = set(right[on].drop_nulls().to_list())
    unmatched = len(right_keys - left_keys)
    fanout = right.group_by(on).len()["len"].max() or 0
    return {
        "on": on,
        "left_unique": left[on].drop_nulls().len() == len(left_keys),
        "right_max_fanout": int(fanout),
        "unmatched_right_rate": round(unmatched / max(1, len(right_keys)), 4),
        "cardinality": "one-to-many" if fanout > 1 else ("one-to-one" if left_keys.len() == right_keys.len() else "many-to-one"),
        "note": "revalidate when either dataset changes; never join on similar column names alone",
    }
