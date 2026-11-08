"""Past-information-only RSI features for an isolated exploratory experiment.

No files are read or written here. Inputs follow ``category_data`` conventions:
monthly ONS index mappings and genuine weekly ``week_end``/``value`` frames.
The weekly quotes are source weekly means (FX is a ratio of means), not claimed
Friday closing prices. Availability buffers are assumptions on current archives,
not recovered historical vintages. RSI is a feature, not a trading rule.
"""
from __future__ import annotations

import calendar
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from shrinkflation.category_data import CATEGORIES, SERIES


CPI_FEATURE = "history_cpi_rsi_6m"
FEATURE_POLICY = {
    "weekly_periods": 14,
    "monthly_periods": 6,
    "weekly_issue_lags_calendar_months": [0, 3],
    "seed": "SMA of the first n raw-level gains/losses across n+1 contiguous samples",
    "recurrence": "Wilder alpha=1/n after the SMA seed",
    "flat_policy": "50 when both smoothed gain and loss are zero",
    "gap_policy": "Exact seven-day weekly or consecutive-calendar-month spacing; any gap/invalid level resets the entire chain; no filling",
    "weekly_staleness_days": 35,
    "weekly_source_semantics": "RSI of genuine weekly source means; FX is the existing ratio of weekly means, not a closing-price RSI",
    "publication_policy": "Existing 7-day ICCO/ECB and 14-day EU buffers; re-evaluated at each actual or lagged issue cutoff",
    "cpi_policy": "Endpoint is no later than both row.latest_known_cpi_month and issue month minus two; conservative month+2 availability",
    "availability_status": "current_archive_with_assumed_buffers_not_original_vintages",
}


def _as_date(value) -> date:
    return pd.Timestamp(value).date()


def _month_start_shift(value: date, months: int) -> date:
    number = value.year * 12 + value.month - 1 + months
    return date(number // 12, number % 12 + 1, 1)


def subtract_calendar_months(value: date, months: int) -> date:
    """Shift an issue date while preserving its day, clamped at month end."""
    shifted = _month_start_shift(value, -months)
    return shifted.replace(day=min(value.day, calendar.monthrange(shifted.year, shifted.month)[1]))


def _normalise_levels(levels: pd.Series) -> pd.Series:
    values = pd.Series(levels, copy=True)
    values.index = pd.DatetimeIndex([_as_date(value) for value in values.index])
    if values.index.duplicated().any():
        raise ValueError("Duplicate source period dates are ambiguous")
    values = pd.to_numeric(values, errors="coerce").astype(float).sort_index()
    return values


def _consecutive(previous: date, current: date, frequency: str) -> bool:
    if frequency == "weekly":
        return current - previous == timedelta(days=7)
    if frequency == "monthly":
        return previous.day == current.day == 1 and _month_start_shift(previous, 1) == current
    raise ValueError("frequency must be 'weekly' or 'monthly'")


def _rsi_value(gain: float, loss: float) -> float:
    if loss == 0:
        return 50.0 if gain == 0 else 100.0
    if gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _rsi_details(levels: pd.Series, periods: int, frequency: str) -> pd.DataFrame:
    if not isinstance(periods, int) or isinstance(periods, bool) or periods < 1:
        raise ValueError("periods must be a positive integer")
    if frequency not in {"weekly", "monthly"}:
        raise ValueError("frequency must be 'weekly' or 'monthly'")
    levels = _normalise_levels(levels)
    previous_date, previous_level = None, None
    gain_sum = loss_sum = average_gain = average_loss = 0.0
    count = 0
    chain_start = None
    rows = []
    for timestamp, level in levels.items():
        current = timestamp.date()
        valid = math.isfinite(level) and level > 0
        if not valid:
            previous_date = previous_level = chain_start = None
            gain_sum = loss_sum = average_gain = average_loss = 0.0
            count = 0
            rsi = np.nan
        elif previous_date is None or not _consecutive(previous_date, current, frequency):
            previous_date, previous_level, chain_start = current, level, current
            gain_sum = loss_sum = average_gain = average_loss = 0.0
            count = 1
            rsi = np.nan
        else:
            delta = level - previous_level
            gain, loss = max(delta, 0.0), max(-delta, 0.0)
            count += 1
            deltas = count - 1
            if deltas <= periods:
                gain_sum += gain
                loss_sum += loss
                if deltas == periods:
                    average_gain, average_loss = gain_sum / periods, loss_sum / periods
            else:
                average_gain = ((periods - 1) * average_gain + gain) / periods
                average_loss = ((periods - 1) * average_loss + loss) / periods
            rsi = _rsi_value(average_gain, average_loss) if deltas >= periods else np.nan
            previous_date, previous_level = current, level
        rows.append({"rsi": rsi, "contiguous_samples": count,
                     "chain_start": chain_start.isoformat() if chain_start else None,
                     "valid_source_value": valid})
    return pd.DataFrame(rows, index=levels.index,
                        columns=["rsi", "contiguous_samples", "chain_start", "valid_source_value"])


def wilder_rsi(levels: pd.Series, periods: int, frequency: str) -> pd.Series:
    """Causal SMA-seeded Wilder RSI, with a complete reset at any period gap.

    Output is date-indexed and sorted. Missing/non-positive/non-finite levels
    reset the chain just like absent dates. No observation is forward-filled.
    A 14-period RSI requires 15 consecutive source levels after each reset.
    """
    return _rsi_details(levels, periods, frequency)["rsi"].rename("rsi")


def _weekly_name(key: str, lag: int) -> str:
    name = f"commodity_{key}_rsi_14w"
    return name if lag == 0 else name + f"_issue_lag{lag}m"


def _audit(row_position: int, row_index, row: pd.Series, feature: str,
           source: str, frequency: str, periods: int, cutoff: date, lag: int = 0,
           buffer_days: int | None = None) -> dict:
    return {"row_position": row_position, "row_index": str(row_index),
            "category_id": row["category_id"], "target_month": row["target_month"],
            "forecast_cutoff": row["forecast_cutoff"], "feature_name": feature,
            "source_key": source, "source_frequency": frequency, "periods": periods,
            "required_contiguous_samples": periods + 1,
            "issue_lag_calendar_months": lag, "effective_cutoff": cutoff.isoformat(),
            "availability_buffer_days": buffer_days, "observation_end": None,
            "source_available_date": None, "source_age_days": None,
            "available_observations": 0, "contiguous_samples": 0,
            "chain_start": None, "cpi_ceiling_month": None,
            "requested_cpi_endpoint": None, "value": np.nan, "status": None}


def _set_endpoint_audit(audit: dict, available: pd.DataFrame, cutoff: date,
                        buffer_days: int | None = None) -> pd.Series:
    latest = available.iloc[-1]
    endpoint = available.index[-1].date()
    audit.update({"observation_end": endpoint.isoformat(),
                  "source_age_days": (cutoff - endpoint).days,
                  "available_observations": len(available),
                  "contiguous_samples": int(latest["contiguous_samples"]),
                  "chain_start": latest["chain_start"]})
    if buffer_days is not None:
        audit["source_available_date"] = (endpoint + timedelta(days=buffer_days)).isoformat()
    return latest


def build_rsi_features(frame: pd.DataFrame, indices: dict[str, dict[date, float]],
                       inputs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Append fixed RSI features without changing any existing frame value/dtype.

    Returns ``(enhanced, long_availability_audit, feature_groups_by_category)``.
    Every new column has one audit row per input row, including explicit
    inapplicable/missing/warmup/stale statuses. Inputs are not mutated. No target
    label is inspected, and no rows are dropped for unavailable RSI features.
    """
    required = {"category_id", "target_month", "forecast_cutoff", "latest_known_cpi_month"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing base columns: {sorted(required - set(frame.columns))}")
    names = [_weekly_name(key, lag) for key in SERIES for lag in (0, 3)] + [CPI_FEATURE]
    collisions = set(names).intersection(frame.columns)
    if collisions:
        raise ValueError(f"RSI feature columns already exist: {sorted(collisions)}")
    enhanced = frame.copy(deep=True)
    for name in names:
        enhanced[name] = np.nan
    weekly = {}
    for key in SERIES:
        if key not in inputs:
            continue
        source = inputs[key]
        if not {"week_end", "value"}.issubset(source.columns):
            raise ValueError(f"Weekly source {key} needs week_end and value")
        levels = pd.Series(source["value"].to_numpy(copy=True), index=source["week_end"])
        weekly[key] = _rsi_details(levels, 14, "weekly")
    monthly = {category: _rsi_details(pd.Series(levels, dtype=float), 6, "monthly")
               for category, levels in indices.items()}
    audit_rows = []
    for position, (row_index, row) in enumerate(frame.iterrows()):
        category = row["category_id"]
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category: {category}")
        cutoff = _as_date(row["forecast_cutoff"])
        for key, spec in SERIES.items():
            for lag in (0, 3):
                effective_cutoff = subtract_calendar_months(cutoff, lag)
                feature = _weekly_name(key, lag)
                record = _audit(position, row_index, row, feature, key, "weekly", 14,
                                effective_cutoff, lag, spec["buffer"])
                if category not in spec["categories"]:
                    record["status"] = "inapplicable"
                elif key not in weekly:
                    record["status"] = "missing_source"
                else:
                    deadline = pd.Timestamp(effective_cutoff - timedelta(days=spec["buffer"]))
                    available = weekly[key].loc[weekly[key].index <= deadline]
                    if available.empty:
                        record["status"] = "no_published_observations"
                    else:
                        latest = _set_endpoint_audit(record, available, effective_cutoff, spec["buffer"])
                        if record["source_age_days"] > 35:
                            record["status"] = "stale"
                        elif not latest["valid_source_value"]:
                            record["status"] = "invalid_source_value"
                        elif pd.isna(latest["rsi"]):
                            record["status"] = "insufficient_contiguous_history"
                        else:
                            record.update({"status": "ok", "value": float(latest["rsi"])})
                enhanced.iat[position, enhanced.columns.get_loc(feature)] = record["value"]
                audit_rows.append(record)
        record = _audit(position, row_index, row, CPI_FEATURE, f"ons_{category}", "monthly", 6, cutoff)
        ceiling = _month_start_shift(cutoff, -2)
        record["cpi_ceiling_month"] = ceiling.isoformat()
        declared = row["latest_known_cpi_month"]
        if pd.isna(declared):
            record["status"] = "no_known_cpi_month"
        elif category not in monthly:
            record["status"] = "missing_source"
        else:
            requested = min(_as_date(declared).replace(day=1), ceiling)
            record["requested_cpi_endpoint"] = requested.isoformat()
            source = monthly[category]
            available = source.loc[source.index <= pd.Timestamp(requested)]
            if available.empty:
                record["status"] = "no_published_observations"
            else:
                latest = _set_endpoint_audit(record, available, cutoff)
                actual = available.index[-1].date()
                published = _month_start_shift(actual, 2)
                record["source_available_date"] = published.isoformat()
                if actual != requested:
                    record["status"] = "missing_cpi_endpoint"
                elif published > cutoff:
                    record["status"] = "not_yet_published"
                elif not latest["valid_source_value"]:
                    record["status"] = "invalid_source_value"
                elif pd.isna(latest["rsi"]):
                    record["status"] = "insufficient_contiguous_history"
                else:
                    record.update({"status": "ok", "value": float(latest["rsi"])})
        enhanced.iat[position, enhanced.columns.get_loc(CPI_FEATURE)] = record["value"]
        audit_rows.append(record)
    groups = {}
    for category in CATEGORIES:
        commodities = [_weekly_name(key, lag) for key, spec in SERIES.items()
                       if category in spec["categories"] for lag in (0, 3)]
        groups[category] = {"rsi_only": commodities + [CPI_FEATURE],
                            "rsi_commodities": commodities, "rsi_cpi": [CPI_FEATURE]}
    # Check exact values, dtypes, column order and index, including categorical
    # and extension dtypes, instead of reconstructing original rows from dicts.
    pd.testing.assert_frame_equal(enhanced.loc[:, frame.columns], frame, check_exact=True)
    return enhanced, pd.DataFrame(audit_rows), groups
