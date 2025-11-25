import json
import os
from datetime import datetime, timedelta, timezone

import streamlit as st


dhaka_tz = timezone(timedelta(hours=6))

DEVICE_FILE = "devices.json"


def parse_metrics(status_json: dict):

    result = status_json.get("result", [])
    m = {x.get("code"): x.get("value") for x in result}

    raw_voltage = m.get("cur_voltage") or 0
    raw_power = m.get("cur_power") or 0
    raw_current = m.get("cur_current") or 0
    raw_add_ele = m.get("add_ele") or 0

    voltage = raw_voltage / 10.0
    power = raw_power / 10.0
    current = raw_current / 1000.0
    energy_kwh = raw_add_ele / 1000.0

    return voltage, current, power, energy_kwh


def build_doc(device_id: str, device_name: str, v: float, c: float, p: float, e: float):

    return {
        "timestamp": datetime.now(dhaka_tz),
        "device_id": device_id,
        "device_name": device_name or "",
        "voltage": v,
        "current": c,
        "power": p,
        "energy_kWh": e,
    }




def load_devices_local():
    if not os.path.exists(DEVICE_FILE):
        return []
    with open(DEVICE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_devices_local(devices):
    with open(DEVICE_FILE, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=4)
