from __future__ import annotations

from typing import Optional


def periods_overlap(
    s1: Optional[str], e1: Optional[str], s2: Optional[str], e2: Optional[str]
) -> bool:
    """True if interval [s1, e1] overlaps with [s2, e2]. None means unbounded."""
    cond1 = (s1 is None) or (e2 is None) or (s1 <= e2)
    cond2 = (e1 is None) or (s2 is None) or (e1 >= s2)
    return cond1 and cond2


def temporal_ranges_overlap(
    s1_min: Optional[str],
    e1_max: Optional[str],
    s2_min: Optional[str],
    e2_max: Optional[str],
) -> bool:
    """True if effective temporal range [s1_min, e1_max] overlaps with [s2_min, e2_max].

    None means unbounded.
    """
    return periods_overlap(s1_min, e1_max, s2_min, e2_max)
