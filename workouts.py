#!/usr/bin/env python3
"""Push structured running workouts to Garmin Connect and schedule them on your watch's calendar.

Workouts live in a JSON file your AI assistant writes after you talk through the plan
(see examples/workouts.json). Each one has a stable `key` and a `revision`: when the revision
changes, the old workout is deleted from Garmin and the new one takes its place. What was sent
is tracked in a state file, so running it twice does nothing.

Usage: python3 workouts.py workouts.json [--state garmin-workouts-state.json] [--dry-run]

Step fields:
  type        warmup | interval | recovery | cooldown | open (open ends on the lap button)
  distance    "5km"            or   duration  "10min"
  pace        "5:30-6:00"      (min/km, fast-slow)   or   hr  "120-150" (bpm)
  note        shown on the watch
"""

import argparse
import json
from pathlib import Path

from auth import get_client

RUN = {"sportTypeId": 1, "sportTypeKey": "running"}
STEP_TYPES = {"warmup": (1, "warmup"), "cooldown": (2, "cooldown"), "interval": (3, "interval"),
              "recovery": (4, "recovery"), "open": (3, "interval")}


def pace_ms(mmss):  # "6:05" -> metres per second
    m, s = map(int, mmss.split(":"))
    return round(1000 / (m * 60 + s), 3)


def build_step(order, p):
    kid, key = STEP_TYPES[p["type"]]
    st = {"type": "ExecutableStepDTO", "stepOrder": order,
          "stepType": {"stepTypeId": kid, "stepTypeKey": key},
          "description": p.get("note", "")[:512],
          "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}}
    if p["type"] == "open":
        st["endCondition"] = {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
    elif "duration" in p:
        st["endCondition"] = {"conditionTypeId": 2, "conditionTypeKey": "time"}
        st["endConditionValue"] = int(p["duration"].replace("min", "")) * 60
    else:
        st["endCondition"] = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
        st["endConditionValue"] = float(p["distance"].replace("km", "")) * 1000
    if p.get("pace"):
        fast, slow = p["pace"].replace("/km", "").split("-")
        st["targetType"] = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
        st["targetValueOne"], st["targetValueTwo"] = pace_ms(slow), pace_ms(fast)
    elif p.get("hr"):
        low, high = p["hr"].split("-")
        st["targetType"] = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
        st["targetValueOne"], st["targetValueTwo"] = int(low), int(high)
    return st


def build_workout(w):
    steps = [build_step(i, p) for i, p in enumerate(w["steps"], 1)]
    return {"workoutName": w["name"], "description": w.get("description", ""), "sportType": RUN,
            "workoutSegments": [{"segmentOrder": 1, "sportType": RUN, "workoutSteps": steps}]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workouts", help="JSON file with the workouts to send")
    ap.add_argument("--state", default="garmin-workouts-state.json", help="what was already sent")
    ap.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
    args = ap.parse_args()

    workouts = json.loads(Path(args.workouts).read_text())
    state_path = Path(args.state).expanduser()
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    g = None if args.dry_run else get_client()

    for w in sorted(workouts, key=lambda w: w["date"]):
        rev = str(w.get("revision", 1))
        prev = state.get(w["key"])
        if prev and prev["revision"] == rev:
            print(f"= {w['date']} {w['name']} (already sent, {prev['workout_id']})")
            continue
        payload = build_workout(w)
        if args.dry_run:
            print(f"~ {w['date']} {w['name']}: {len(payload['workoutSegments'][0]['workoutSteps'])} steps")
            continue
        try:
            if prev:  # new revision: drop the old one from Garmin first
                g.garth.delete("connectapi", f"/workout-service/workout/{prev['workout_id']}", api=True)
            wid = g.garth.post("connectapi", "/workout-service/workout", json=payload, api=True).json()["workoutId"]
            g.garth.post("connectapi", f"/workout-service/schedule/{wid}", json={"date": w["date"]}, api=True)
            state[w["key"]] = {"workout_id": wid, "revision": rev, "date": w["date"], "name": w["name"]}
            print(f"+ {w['date']} {w['name']} -> {wid}")
        except Exception as e:
            print(f"! {w['date']} {w['name']}: {e}")

    if not args.dry_run:
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
