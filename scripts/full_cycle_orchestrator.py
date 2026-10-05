#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Moscow")
STATE_FILE = Path("full_cycle_state.json")
WEBHOOK = os.environ.get(
    "ECOFLOT_WEBHOOK",
    "https://script.google.com/macros/s/AKfycbzDedkBi9soafe6DuR0TX0Enpg0vcgX87gNyOLsl30kL4COSuwdmPWO64c1ZzNodmFlRg/exec",
)

CONTOURS = [
    ("Internet Leads", [["python3", "scripts/internet_leads_monitor.py"]], ["internet_leads_state.json"], 720),
    ("Telegram/MAX/VK", [
        ["python3", "scripts/social_leads_monitor.py"],
        ["python3", "scripts/max_leads_monitor.py"],
    ], ["social_public_leads_state.json", "max_public_leads_state.json"], 360),
    ("Tender Watch", [["python3", "scripts/tender_monitor.py"]], ["tender_state.json"], 720),
    ("Object Leads", [["python3", "scripts/object_leads_monitor.py"]], ["object_leads_state.json"], 360),
]

def cycle_key(now=None):
    now = now or datetime.now(TZ)
    slots = [8, 14, 18]
    eligible = [h for h in slots if h <= now.hour]
    if not eligible:
        prev = now.replace(day=now.day)  # schedule never calls before 08:00
        return prev.strftime("%Y-%m-%d") + " 08:00"
    return now.strftime("%Y-%m-%d") + f" {max(eligible):02d}:00"

def load_json(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return {}

def save_state(data):
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")

def aggregate(paths):
    sent = candidates = errors = 0
    unchecked = []
    found = False
    for path in paths:
        state = load_json(path)
        last = state.get("last_run") or {}
        if last:
            found = True
        sent += int(last.get("sent", 0) or 0)
        candidates += int(last.get("candidates", 0) or 0)
        errors += int(last.get("errors", 0) or 0)
        raw = last.get("unchecked_sources") or last.get("unverified_sources") or []
        if isinstance(raw, str):
            raw = [raw]
        unchecked.extend(str(x) for x in raw if x)
    return {
        "new": sent,
        "duplicates": max(candidates - sent, 0),
        "errors": errors,
        "unchecked_sources": sorted(set(unchecked)),
        "state_found": found,
    }

def main():
    cycle = os.environ.get("ECOFLOT_CYCLE_KEY", "").strip() or cycle_key()
    existing = load_json(STATE_FILE)
    if existing.get("cycleKey") == cycle and existing.get("status") in {"COMPLETE", "SEARCH_COMPLETE", "DELIVERY_PENDING"}:
        print("CYCLE_ALREADY_RECORDED", cycle, existing.get("status"))
        return 0

    state = {
        "cycleKey": cycle,
        "started_at": datetime.now(TZ).isoformat(),
        "status": "STARTED",
        "contours": {},
    }
    save_state(state)

    env = os.environ.copy()
    env["ECOFLOT_CYCLE_KEY"] = cycle
    env["SUPPRESS_NO_RESULTS"] = "1"
    env["ECOFLOT_ORCHESTRATED"] = "1"

    any_failed = False
    for name, commands, state_paths, timeout_seconds in CONTOURS:
        print("START_CONTOUR", name, cycle, flush=True)
        exit_codes = []
        for cmd in commands:
            try:
                proc = subprocess.run(cmd, env=env, text=True, timeout=timeout_seconds)
                exit_codes.append(proc.returncode)
            except subprocess.TimeoutExpired:
                print("CONTOUR_TIMEOUT", name, cmd, timeout_seconds, flush=True)
                exit_codes.append(124)
        result = aggregate(state_paths)
        result["exit_codes"] = exit_codes
        result["status"] = "ok" if all(code == 0 for code in exit_codes) and result["state_found"] else "error"
        if result["status"] != "ok":
            any_failed = True
        state["contours"][name] = result
        save_state(state)
        print("END_CONTOUR", name, json.dumps(result, ensure_ascii=False), flush=True)

    state["search_finished_at"] = datetime.now(TZ).isoformat()
    state["status"] = "SEARCH_FAILED" if any_failed else "SEARCH_COMPLETE"
    state["totals"] = {
        "new": sum(x.get("new", 0) for x in state["contours"].values()),
        "duplicates": sum(x.get("duplicates", 0) for x in state["contours"].values()),
        "unchecked_sources": sorted({
            src for x in state["contours"].values() for src in x.get("unchecked_sources", [])
        }),
    }

    # Each contour sends verified real records directly through its own webhook path.
    # Do NOT POST mode=process-outbox to the generic Apps Script endpoint:
    # the deployed handler can interpret that payload as a lead and create garbage rows.
    state["delivery"] = {
        "ok": True,
        "mode": "inline-per-record",
        "note": "No generic process-outbox webhook call",
    }
    state["finished_at"] = datetime.now(TZ).isoformat()
    save_state(state)

    print("FULL_CYCLE_STATE", json.dumps(state, ensure_ascii=False), flush=True)
    return 1 if any_failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
