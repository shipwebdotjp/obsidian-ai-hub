"""Healthcare overview service — on-the-fly aggregation over healthcare.sqlite3.

Phase 1: curated Quantity types only (value_numeric). Category types (sleep/stand)
require duration computation and are deferred.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from obsidian_ai_hub.healthcare import queries as hc_queries
from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

# Curated metrics for Phase 1: Quantity types only.
CURATED_METRICS: list[dict[str, str]] = [
    {
        "key": "steps",
        "label": "歩数",
        "type": "HKQuantityTypeIdentifierStepCount",
        "unit": "count",
        "aggregation": "sum",
    },
    {
        "key": "heart_rate",
        "label": "心拍数",
        "type": "HKQuantityTypeIdentifierHeartRate",
        "unit": "count/min",
        "aggregation": "avg",
    },
    {
        "key": "resting_heart_rate",
        "label": "安静時心拍数",
        "type": "HKQuantityTypeIdentifierRestingHeartRate",
        "unit": "count/min",
        "aggregation": "avg",
    },
    {
        "key": "hrv",
        "label": "心拍変動",
        "type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
        "unit": "ms",
        "aggregation": "avg",
    },
    {
        "key": "active_energy",
        "label": "アクティブエネルギー",
        "type": "HKQuantityTypeIdentifierActiveEnergyBurned",
        "unit": "kcal",
        "aggregation": "sum",
    },
    {
        "key": "basal_energy",
        "label": "基礎代謝エネルギー",
        "type": "HKQuantityTypeIdentifierBasalEnergyBurned",
        "unit": "kcal",
        "aggregation": "sum",
    },
    {
        "key": "distance",
        "label": "歩行+走行距離",
        "type": "HKQuantityTypeIdentifierDistanceWalkingRunning",
        "unit": "km",
        "aggregation": "sum",
    },
    {
        "key": "flights",
        "label": "上った階数",
        "type": "HKQuantityTypeIdentifierFlightsClimbed",
        "unit": "count",
        "aggregation": "sum",
    },
    {
        "key": "exercise_time",
        "label": "エクササイズ時間",
        "type": "HKQuantityTypeIdentifierAppleExerciseTime",
        "unit": "min",
        "aggregation": "sum",
    },
]


def _validate_date_str(s: object) -> date:
    if not isinstance(s, str):
        raise ValueError("Invalid date format. Use YYYY-MM-DD")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError("Invalid date format. Use YYYY-MM-DD")


def _bucket_key_for_date(d: date, granularity: str) -> str:
    if granularity == "day":
        return d.strftime("%Y-%m-%d")
    if granularity == "week":
        iso_yr, iso_wk, _ = d.isocalendar()
        return f"{iso_yr}-W{iso_wk:02d}"
    return d.strftime("%Y-%m")


def get_healthcare_overview(
    start_date_str: str,
    end_date_str: str,
) -> dict:
    """Return overview timeseries for all curated metrics.

    Raises ValueError on invalid input; caller maps to HTTP 400.
    """
    start_date = _validate_date_str(start_date_str)
    end_date = _validate_date_str(end_date_str)

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    duration = (end_date - start_date).days + 1
    if duration > 3660:
        raise ValueError("Date range exceeds maximum limit of 10 years (3660 days)")

    # Granularity mirrors dashboard but with healthcare-typical threshold:
    # daily is most natural for wellness. Keep daily up to 60 days,
    # weekly up to ~1 year, monthly beyond.
    if duration <= 60:
        granularity: str = "day"
    elif duration <= 366:
        granularity = "week"
    else:
        granularity = "month"

    # Build bucket definitions (continuous, gap-filled) for the chosen granularity.
    buckets_by_key: dict[str, dict] = {}
    date_list: list[date] = []
    curr = start_date
    while curr <= end_date:
        date_list.append(curr)
        curr += timedelta(days=1)

    for d in date_list:
        d_str = d.strftime("%Y-%m-%d")
        if granularity == "day":
            b_key = d_str
            b_start = d_str
            b_end = d_str
            b_label = d.strftime("%m/%d")
        elif granularity == "week":
            iso_yr, iso_wk, _ = d.isocalendar()
            b_key = f"{iso_yr}-W{iso_wk:02d}"
            mon = d - timedelta(days=d.weekday())
            sun = mon + timedelta(days=6)
            # Clamp to the requested window so partial weeks aren't mislabeled
            # (boundaries are week-aligned for full middle weeks).
            b_start = max(mon, start_date).strftime("%Y-%m-%d")
            b_end = min(sun, end_date).strftime("%Y-%m-%d")
            b_label = f"W{iso_wk:02d}"
        else:  # month
            b_key = _bucket_key_for_date(d, granularity)
            _, last_day = calendar.monthrange(d.year, d.month)
            b_start = f"{b_key}-01"
            b_end = f"{b_key}-{last_day:02d}"
            b_label = d.strftime("%Y/%m")

        if b_key not in buckets_by_key:
            buckets_by_key[b_key] = {
                "key": b_key,
                "display_label": b_label,
                "start_date": b_start,
                "end_date": b_end,
            }

    sorted_keys = sorted(buckets_by_key.keys())
    # Pre-create empty bucket templates per metric after query, but share keys.

    conn = get_healthcare_db_connection()
    try:
        # Single grouped query for all curated types to avoid N+1 scans.
        daily_by_type = hc_queries.get_daily_aggregates_multi(
            conn,
            types=[m["type"] for m in CURATED_METRICS],
            start_date=start_date_str,
            end_date=end_date_str,
        )
        metrics_out: list[dict] = []
        for mdef in CURATED_METRICS:
            type_ = mdef["type"]
            aggregation = mdef["aggregation"]
            daily = daily_by_type.get(type_, {})
            # Accumulate per bucket: need sum/count/min/max per bucket to allow
            # both sum and avg rollups.
            accum: dict[str, dict] = {}
            for k in sorted_keys:
                accum[k] = {"sum": 0.0, "count": 0, "min": None, "max": None}

            for day_str, agg in daily.items():
                # Map day to its bucket key.
                try:
                    day_d = date.fromisoformat(day_str)
                except ValueError:
                    continue
                b_key = _bucket_key_for_date(day_d, granularity)

                if b_key not in accum:
                    # Day outside computed bucket_keys shouldn't happen (we built
                    # buckets for entire range), but skip defensively.
                    continue
                bucket_acc = accum[b_key]
                # agg holds avg/min/max/sum/count for this single day's records.
                # For bucket rollup, combine daily sum/count, min of mins, max of maxs.
                bucket_acc["sum"] += agg["sum"] if agg["sum"] is not None else 0.0
                bucket_acc["count"] += agg["count"]
                if agg["min"] is not None:
                    if bucket_acc["min"] is None or agg["min"] < bucket_acc["min"]:
                        bucket_acc["min"] = agg["min"]
                if agg["max"] is not None:
                    if bucket_acc["max"] is None or agg["max"] > bucket_acc["max"]:
                        bucket_acc["max"] = agg["max"]

            # Build final bucket list in sorted order.
            buckets: list[dict] = []
            for k in sorted_keys:
                meta = buckets_by_key[k]
                a = accum[k]
                cnt = a["count"]
                if cnt == 0:
                    buckets.append(
                        {
                            "key": meta["key"],
                            "display_label": meta["display_label"],
                            "start_date": meta["start_date"],
                            "end_date": meta["end_date"],
                            "value": None,
                            "avg": None,
                            "min": None,
                            "max": None,
                            "sum": None,
                            "count": 0,
                        }
                    )
                else:
                    avg_val = a["sum"] / cnt if cnt else None
                    if aggregation == "sum":
                        primary = a["sum"]
                    else:  # avg
                        primary = avg_val
                    buckets.append(
                        {
                            "key": meta["key"],
                            "display_label": meta["display_label"],
                            "start_date": meta["start_date"],
                            "end_date": meta["end_date"],
                            "value": primary,
                            "avg": avg_val,
                            "min": a["min"],
                            "max": a["max"],
                            "sum": a["sum"],
                            "count": cnt,
                        }
                    )

            # latest / previous / delta
            latest_value = None
            previous_value = None
            delta_pct = None
            # walk backwards to find latest non-null
            latest_idx = -1
            for idx in range(len(buckets) - 1, -1, -1):
                if buckets[idx]["value"] is not None:
                    latest_idx = idx
                    latest_value = buckets[idx]["value"]
                    break
            if latest_idx != -1:
                for idx in range(latest_idx - 1, -1, -1):
                    if buckets[idx]["value"] is not None:
                        previous_value = buckets[idx]["value"]
                        break
                if (
                    latest_value is not None
                    and previous_value is not None
                    and previous_value != 0
                ):
                    delta_pct = round(
                        ((latest_value - previous_value) / abs(previous_value)) * 100, 1
                    )

            metrics_out.append(
                {
                    "key": mdef["key"],
                    "label": mdef["label"],
                    "type": mdef["type"],
                    "unit": mdef["unit"],
                    "aggregation": mdef["aggregation"],
                    "latest_value": latest_value,
                    "previous_value": previous_value,
                    "delta_pct": delta_pct,
                    "buckets": buckets,
                }
            )

        return {
            "start_date": start_date_str,
            "end_date": end_date_str,
            "granularity": granularity,
            "metrics": metrics_out,
        }
    finally:
        conn.close()
