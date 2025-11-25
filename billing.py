from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple

import pandas as pd

from tuya_api_mongo import range_docs, latest_docs
from helpers import dhaka_tz


def _bd_domestic_bill(units_kwh: float) -> float:
    u = max(0.0, float(units_kwh))


    if u <= 50:
        return round(u * 4.633, 2)

    slabs = [
        (75, 5.26),
        (200, 7.20),
        (300, 7.59),
        (400, 8.02),
        (600, 12.67),
        (float("inf"), 14.61),
    ]

    remaining = u
    last_upper = 0.0
    total = 0.0

    for upper, rate in slabs:
        if remaining <= 0:
            break
        span = min(remaining, upper - last_upper)
        if span > 0:
            total += span * rate
            remaining -= span
            last_upper = upper

    return round(total, 2)


def _units_between(df: pd.DataFrame) -> float:
    if df.empty or "energy_kWh" not in df.columns:
        return 0.0
    return float(df["energy_kWh"].max() - df["energy_kWh"].min())


def _day_window_local(now=None) -> Tuple[datetime, datetime]:
    if now is None:
        now = datetime.now(dhaka_tz)

    day_start_local = datetime(now.year, now.month, now.day, tzinfo=dhaka_tz)
    day_end_local = day_start_local.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )

    day_start = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    day_end = day_end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return day_start, day_end


def _month_window_local(now=None) -> Tuple[datetime, datetime]:
    if now is None:
        now = datetime.now(dhaka_tz)

    m_start_local = datetime(now.year, now.month, 1, tzinfo=dhaka_tz)
    if now.month == 12:
        next_month_local = datetime(now.year + 1, 1, 1, tzinfo=dhaka_tz)
    else:
        next_month_local = datetime(now.year, now.month + 1, 1, tzinfo=dhaka_tz)

    m_start = m_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    m_end = next_month_local.astimezone(timezone.utc).replace(tzinfo=None)
    return m_start, m_end




def daily_monthly_for(device_id: str):
    now = datetime.now(dhaka_tz)

    # Today
    day_start, day_end = _day_window_local(now)
    ddf = range_docs(device_id, day_start, day_end)
    d_units = round(_units_between(ddf), 3)
    d_cost = _bd_domestic_bill(d_units)

    # Month
    m_start, m_end = _month_window_local(now)
    mdf = range_docs(device_id, m_start, m_end)
    m_units = round(_units_between(mdf), 3)
    m_cost = _bd_domestic_bill(m_units)

    return d_units, d_cost, m_units, m_cost


def _latest_power_voltage(device_id: str):
    df = latest_docs(device_id, n=1)
    if df.empty:
        return 0.0, None
    row = df.iloc[-1]
    p = float(row.get("power", 0) or 0)
    v = row.get("voltage", None)
    v = float(v) if v is not None else None
    return p, v


def aggregate_totals_all_devices(devices: List[Dict]) -> tuple:

    dev_ids = [d["id"] if isinstance(d, dict) else d for d in devices]

    # Instant totals
    total_power_now = 0.0
    latest_voltages = []
    for did in dev_ids:
        p, v = _latest_power_voltage(did)
        total_power_now += p
        if v is not None:
            latest_voltages.append(float(v))
    present_voltage = round(max(latest_voltages), 2) if latest_voltages else 0.0

    now = datetime.now(dhaka_tz)

    # Today totals
    day_start, day_end = _day_window_local(now)
    total_kwh_today = 0.0
    for did in dev_ids:
        ddf = range_docs(did, day_start, day_end)
        total_kwh_today += _units_between(ddf)
    total_kwh_today = round(total_kwh_today, 3)
    today_bill_bdt = _bd_domestic_bill(total_kwh_today)

    # Month totals
    m_start, m_end = _month_window_local(now)
    total_kwh_month = 0.0
    for did in dev_ids:
        mdf = range_docs(did, m_start, m_end)
        total_kwh_month += _units_between(mdf)
    total_kwh_month = round(total_kwh_month, 3)
    month_bill_bdt = _bd_domestic_bill(total_kwh_month)

    return (
        round(total_power_now, 2),
        present_voltage,
        total_kwh_today,
        today_bill_bdt,
        total_kwh_month,
        month_bill_bdt,
    )


def aggregate_timeseries_24h(devices: List[Dict], resample_rule: str = "5T") -> pd.DataFrame:
    dev_ids = [d["id"] if isinstance(d, dict) else d for d in devices]
    end = datetime.now()
    start = end - timedelta(hours=24)

    frames = []
    for did in dev_ids:
        df = range_docs(did, start, end)
        if df.empty:
            continue
        cols = [c for c in ["timestamp", "power", "voltage"] if c in df.columns]
        if "timestamp" not in cols:
            continue
        df = df[cols].sort_values("timestamp").set_index("timestamp")
        df = df.resample(resample_rule).mean(numeric_only=True)
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "power_sum_W", "voltage_avg_V"])

    aligned = pd.concat(frames, axis=1, keys=range(len(frames)))
    power_cols = [c for c in aligned.columns if c[1] == "power"]
    voltage_cols = [c for c in aligned.columns if c[1] == "voltage"]

    out = pd.DataFrame(
        {
            "power_sum_W": aligned[power_cols].sum(axis=1, min_count=1),
            "voltage_avg_V": aligned[voltage_cols].mean(axis=1),
        }
    )
    out = out.dropna(how="all")
    out = out.reset_index().rename(columns={"index": "timestamp"})
    return out


def aggregate_timeseries_for_day(
    devices: List[Dict],
    day_local,
    resample_rule: str = "5T",
) -> pd.DataFrame:
    if not devices:
        return pd.DataFrame(columns=["timestamp", "power_sum_W", "voltage_avg_V"])

    if isinstance(day_local, datetime):
        day = day_local.date()
    else:
        day = day_local

    start_local = datetime(day.year, day.month, day.day, tzinfo=dhaka_tz)
    end_local = start_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    dev_ids = [d["id"] if isinstance(d, dict) else d for d in devices]
    frames = []
    for did in dev_ids:
        df = range_docs(did, start, end)
        if df.empty:
            continue
        cols = [c for c in ["timestamp", "power", "voltage"] if c in df.columns]
        if "timestamp" not in cols:
            continue
        df = df[cols].sort_values("timestamp").set_index("timestamp")
        df = df.resample(resample_rule).mean(numeric_only=True)
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "power_sum_W", "voltage_avg_V"])

    aligned = pd.concat(frames, axis=1, keys=range(len(frames)))
    power_cols = [c for c in aligned.columns if c[1] == "power"]
    voltage_cols = [c for c in aligned.columns if c[1] == "voltage"]

    out = pd.DataFrame(
        {
            "power_sum_W": aligned[power_cols].sum(axis=1, min_count=1),
            "voltage_avg_V": aligned[voltage_cols].mean(axis=1),
        }
    )
    out = out.dropna(how="all")
    out = out.reset_index().rename(columns={"index": "timestamp"})
    return out
