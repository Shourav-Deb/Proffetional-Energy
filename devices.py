import json
from pathlib import Path
from typing import List, Dict, Optional

DEVICES_JSON_PATH = Path("devices.json")


def load_devices() -> List[Dict]:
    """Return list of devices [{'name': ..., 'id': ..., 'building': ..., 'floor': ..., 'room': ...}, ...]."""
    if not DEVICES_JSON_PATH.exists():
        return []
    try:
        return json.loads(DEVICES_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_devices(devs: List[Dict]) -> None:
    """Overwrite devices.json with new list."""
    DEVICES_JSON_PATH.write_text(json.dumps(devs, indent=4), encoding="utf-8")


def get_device_by_id(device_id: str) -> Optional[Dict]:
    """Return device dict for given Tuya device_id, or None if not found."""
    for d in load_devices():
        if d.get("id") == device_id:
            return d
    return None


def group_devices_by_floor() -> Dict[str, List[Dict]]:
    """
    Group devices by 'building-floor' key so we can aggregate easily.

    Returns: { "FUB-4": [device1, device2, ...], "FUB-5": [...] }
    """
    floors: Dict[str, List[Dict]] = {}
    for d in load_devices():
        building = d.get("building", "FUB")
        floor = d.get("floor", "Unknown")
        key = f"{building}-{floor}"
        floors.setdefault(key, []).append(d)
    return floors
