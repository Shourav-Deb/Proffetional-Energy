from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from typing import List, Dict, Optional

from bson import ObjectId
from pymongo.errors import PyMongoError

from helpers import dhaka_tz
from tuya_api_mongo import get_client, MONGODB_DB
from tuya_api import get_token, control_device


def _get_db_and_collections():
    client = get_client()
    if client is None:
        return None, None, None
    db = client[MONGODB_DB]
    schedules = db["schedules"]
    logs = db["schedule_logs"]
    return db, schedules, logs


def list_schedules(device_id: Optional[str] = None) -> List[Dict]:
    _, schedules, _ = _get_db_and_collections()
    if schedules is None:
        return []
    query = {}
    if device_id:
        query["device_id"] = device_id
    try:
        docs = list(schedules.find(query).sort("created_at", -1))
    except PyMongoError:
        return []
    return docs


def create_schedule(
    device_id: str,
    device_name: str,
    building: str,
    floor: str,
    room: str,
    action: str,
    kind: str,
    date_value,
    time_value: dtime,
    weekdays: Optional[List[int]] = None,
) -> Optional[str]:
    _, schedules, _ = _get_db_and_collections()
    if schedules is None:
        return None

    if action not in ("on", "off"):
        raise ValueError("action must be 'on' or 'off'")
    if kind not in ("once", "weekly"):
        raise ValueError("kind must be 'once' or 'weekly'")

    if kind == "once" and date_value is None:
        raise ValueError("date_value is required for one-time schedule")

    doc: Dict = {
        "device_id": device_id,
        "device_name": device_name,
        "building": building,
        "floor": floor,
        "room": room,
        "action": action,
        "kind": kind,
        "time_str": time_value.strftime("%H:%M"),
        "is_active": True,
        "created_at": datetime.now(dhaka_tz),
        "last_run_at": None,
    }
    if kind == "once":
        doc["date"] = date_value.isoformat()
    else:
        doc["weekdays"] = weekdays or []

    try:
        res = schedules.insert_one(doc)
        return str(res.inserted_id)
    except PyMongoError:
        return None


def update_schedule_active(schedule_id: str, is_active: bool) -> None:
    _, schedules, _ = _get_db_and_collections()
    if schedules is None:
        return
    try:
        schedules.update_one(
            {"_id": ObjectId(schedule_id)},
            {"$set": {"is_active": bool(is_active)}},
        )
    except PyMongoError:
        pass


def delete_schedule(schedule_id: str) -> None:
    _, schedules, _ = _get_db_and_collections()
    if schedules is None:
        return
    try:
        schedules.delete_one({"_id": ObjectId(schedule_id)})
    except PyMongoError:
        pass


def _run_action(doc: Dict) -> None:
    _, _, logs = _get_db_and_collections()
    device_id = doc["device_id"]
    action = doc["action"]
    value = True if action == "on" else False

    try:
        token = get_token()
        res = control_device(device_id, token, "switch_1", value)
    except Exception as e:
        res = {"error": str(e)}

    if logs is not None:
        try:
            logs.insert_one(
                {
                    "schedule_id": doc.get("_id"),
                    "device_id": device_id,
                    "action": action,
                    "executed_at": datetime.now(dhaka_tz),
                    "result": res,
                }
            )
        except PyMongoError:
            pass


def run_due_schedules():
    _, schedules, _ = _get_db_and_collections()
    if schedules is None:
        return

    now_local = datetime.now(dhaka_tz)

    try:
        docs = list(schedules.find({"is_active": True}))
    except PyMongoError:
        return

    for doc in docs:
        kind = doc.get("kind", "once")
        time_str = doc.get("time_str", "00:00")
        try:
            hh, mm = [int(x) for x in time_str.split(":")]
        except Exception:
            hh, mm = 0, 0

        # Last run
        last_run_at = doc.get("last_run_at")
        if last_run_at is not None and not isinstance(last_run_at, datetime):
            last_run_at = None

        if kind == "once":
            date_str = doc.get("date")
            if not date_str:
                continue
            try:
                y, m, d = [int(x) for x in date_str.split("-")]
                sched_dt = datetime(y, m, d, hh, mm, tzinfo=dhaka_tz)
            except Exception:
                continue

            if now_local >= sched_dt:
                if last_run_at is None or last_run_at < sched_dt:
                    _run_action(doc)
                    try:
                        schedules.update_one(
                            {"_id": doc["_id"]},
                            {"$set": {"last_run_at": now_local}},
                        )
                    except PyMongoError:
                        pass

        elif kind == "weekly":
            weekdays = doc.get("weekdays", [])
            if now_local.weekday() not in weekdays:
                continue
            sched_dt = datetime(
                now_local.year,
                now_local.month,
                now_local.day,
                hh,
                mm,
                tzinfo=dhaka_tz,
            )

           
            if now_local >= sched_dt:
                already_today = (
                    last_run_at is not None
                    and last_run_at.astimezone(dhaka_tz).date() == now_local.date()
                )
                if not already_today:
                    _run_action(doc)
                    try:
                        schedules.update_one(
                            {"_id": doc["_id"]},
                            {"$set": {"last_run_at": now_local}},
                        )
                    except PyMongoError:
                        pass
