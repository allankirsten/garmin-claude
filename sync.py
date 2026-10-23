#!/usr/bin/env python3
"""Garmin Connect -> one markdown note an AI assistant can read.

Keeps a local JSON cache (first run backfills HISTORY_DAYS, later runs only fetch what is missing)
and rewrites the note with current status, 30-day averages, a daily table, weekly trends and
monthly HRV. Point OUTPUT at a folder your assistant already reads (an Obsidian vault, a project).

Usage: python3 sync.py [--output Garmin.md] [--cache garmin-cache.json] [--days 365]
"""

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

from auth import get_client


def fetch_body_battery_bulk(g, start, end):
    """date -> {bb_charged, bb_drained}, fetched in 30-day chunks."""
    results = {}
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=29), end)
        try:
            for d in g.get_body_battery(cursor.isoformat(), chunk_end.isoformat()) or []:
                if d.get("charged") is not None:
                    results[d["date"]] = {"bb_charged": d.get("charged"), "bb_drained": d.get("drained")}
        except Exception:
            pass
        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.2)
    return results


def fetch_day(g, d):
    """HRV, stress, daily stats, training readiness, VO2 max and training status for one day."""
    ds = d.isoformat()
    rec = {}

    try:
        s = (g.get_hrv_data(ds) or {}).get("hrvSummary", {})
        rec["hrv_status"] = s.get("status")
        rec["hrv_5min_high"] = s.get("lastNight5MinHigh") or s.get("weekly5DayAverage")
    except Exception:
        pass

    try:
        stress = g.get_stress_data(ds)
        rec["stress_avg"] = stress.get("avgStressLevel")
        rec["stress_max"] = stress.get("maxStressLevel")
        rec["stress_rest_min"] = (stress.get("restStressDuration") or 0) // 60
    except Exception:
        pass

    try:
        stats = g.get_user_summary(ds)
        rec["steps"] = stats.get("totalSteps")
        rec["cal_active"] = stats.get("activeKilocalories")
        rec["cal_total"] = stats.get("totalKilocalories")
        rec["intensity_vig"] = stats.get("vigorousIntensityMinutes")
        rec["intensity_mod"] = stats.get("moderateIntensityMinutes")
    except Exception:
        pass

    try:
        tr = g.get_training_readiness(ds)
        if tr:
            t = tr[0]
            rec["readiness_score"] = t.get("score")
            rec["readiness_level"] = t.get("level")
            rec["readiness_feedback"] = t.get("feedbackShort")
            rec["recovery_time_h"] = round(t["recoveryTime"] / 60, 1) if t.get("recoveryTime") else None
            rec["hrv_weekly_avg"] = t.get("hrvWeeklyAverage")
    except Exception:
        pass

    try:
        ts = g.get_training_status(ds)
        vo2 = (ts.get("mostRecentVO2Max") or {}).get("generic") or {}
        if vo2.get("calendarDate") == ds:
            rec["vo2max"] = vo2.get("vo2MaxPreciseValue")
        latest = (ts.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
        if latest:
            tsd = next(iter(latest.values()))
            rec["training_status"] = tsd.get("trainingStatusFeedbackPhrase")
            acwr = tsd.get("acuteTrainingLoadDTO") or {}
            rec["acwr"] = acwr.get("dailyAcuteChronicWorkloadRatio")
            rec["acwr_status"] = acwr.get("acwrStatus")
            rec["acute_load"] = acwr.get("dailyTrainingLoadAcute")
            rec["chronic_load"] = acwr.get("dailyTrainingLoadChronic")
    except Exception:
        pass

    return rec


def update_cache(g, cache, history_days):
    today = date.today()
    start = today - timedelta(days=history_days)
    all_days = [start + timedelta(days=i) for i in range(history_days + 1)]

    missing_bb = [d for d in all_days if "bb_charged" not in cache.get(d.isoformat(), {})]
    if missing_bb:
        print(f"  Body Battery: {missing_bb[0]} -> {missing_bb[-1]}")
        for ds, vals in fetch_body_battery_bulk(g, missing_bb[0], missing_bb[-1]).items():
            cache.setdefault(ds, {}).update(vals)

    def needs_fetch(d):
        v = cache.get(d.isoformat(), {})
        # Readiness is retried for recent days only: older ones are gone for good if missing.
        return "steps" not in v or ("readiness_score" not in v and d >= today - timedelta(days=60))

    missing = [d for d in all_days if needs_fetch(d)]
    for idx, d in enumerate(missing, 1):
        cache.setdefault(d.isoformat(), {}).update(fetch_day(g, d))
        if idx % 30 == 0 or idx == len(missing):
            print(f"  {idx}/{len(missing)} days ({d})")
        time.sleep(0.3)
    return cache


def build_note(cache, history_days):
    today = date.today()
    start = today - timedelta(days=history_days)
    days = sorted(((ds, v) for ds, v in cache.items() if start.isoformat() <= ds <= today.isoformat()), reverse=True)

    def f(val):
        return "-" if val is None else val

    def avg(values):
        values = [x for x in values if x is not None]
        return round(sum(values) / len(values)) if values else None

    last30 = [v for _, v in days[:30]]
    vo2 = next(((ds, v["vo2max"]) for ds, v in days if v.get("vo2max")), (None, None))
    ts = next((v for _, v in days if v.get("training_status")), {})
    status = (ts.get("training_status") or "-").replace("_1", "").replace("_2", "").replace("_", " ").title()

    daily = []
    for ds, v in days[:30]:
        steps = f"{v['steps']:,}" if v.get("steps") else "-"
        daily.append(
            f"| {ds} | {f(v.get('bb_charged'))}/{f(v.get('bb_drained'))} | {f(v.get('hrv_5min_high'))} "
            f"| {f(v.get('stress_avg'))} | {f(v.get('readiness_score'))} ({v.get('readiness_level') or '-'}) "
            f"| {f(v.get('recovery_time_h'))}h | {steps} |"
        )

    weekly = []
    for w in range(15, -1, -1):
        wend = today - timedelta(weeks=w)
        wdays = [cache.get((wend - timedelta(days=i)).isoformat(), {}) for i in range(7)]
        weekly.append(
            f"| {(wend - timedelta(days=6)).isoformat()} to {wend.isoformat()} "
            f"| {f(avg(d.get('bb_charged') for d in wdays))} | {f(avg(d.get('readiness_score') for d in wdays))} |"
        )

    hrv_by_month = {}
    for ds, v in days:
        if v.get("hrv_5min_high"):
            hrv_by_month.setdefault(ds[:7], []).append(v["hrv_5min_high"])
    monthly = [
        f"| {m} | {round(sum(vals) / len(vals))} ms | {min(vals)} | {max(vals)} | {len(vals)} |"
        for m, vals in sorted(hrv_by_month.items(), reverse=True)[:12]
    ]

    nl = "\n"
    return f"""---
tags: [health, garmin, hrv, body-battery, stress, vo2max, training-readiness]
updated: {today.isoformat()}
---

# Garmin

Synced automatically. Last update: **{today.isoformat()}**.

## Current status

| Metric | Value |
|--------|-------|
| VO2 max | {f(vo2[1])} ml/kg/min (measured {vo2[0] or '-'}) |
| Training status | {status} |
| Acute:chronic load ratio | {f(ts.get('acwr'))} ({ts.get('acwr_status') or '-'}) |

## Last 30 days, averages

| Metric | Average |
|--------|---------|
| Training readiness | {f(avg(v.get('readiness_score') for v in last30))} / 100 |
| Body Battery charged | {f(avg(v.get('bb_charged') for v in last30))} |
| HRV (5 min high) | {f(avg(v.get('hrv_5min_high') for v in last30))} ms |
| Stress | {f(avg(v.get('stress_avg') for v in last30))} |

## Last 30 days

| Date | BB (up/down) | HRV | Stress | Readiness | Recovery | Steps |
|------|--------------|-----|--------|-----------|----------|-------|
{nl.join(daily)}

## Weekly, Body Battery and readiness (16 weeks)

| Week | BB avg | Readiness avg |
|------|--------|---------------|
{nl.join(weekly)}

## Monthly HRV (12 months)

| Month | Average | Min | Max | Days with data |
|-------|---------|-----|-----|----------------|
{nl.join(monthly)}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", default="Garmin.md", help="markdown note to write")
    ap.add_argument("--cache", default="garmin-cache.json", help="local JSON cache")
    ap.add_argument("--days", type=int, default=365, help="history to keep")
    args = ap.parse_args()

    cache_path, output = Path(args.cache).expanduser(), Path(args.output).expanduser()
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    cache = update_cache(get_client(), cache, args.days)
    cache_path.write_text(json.dumps(cache, indent=2))
    output.write_text(build_note(cache, args.days), encoding="utf-8")
    print(f"Garmin sync OK -> {output}")


if __name__ == "__main__":
    main()
