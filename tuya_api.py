import os
import time
import json
import hmac
import hashlib
import requests
from dotenv import load_dotenv


load_dotenv()

try:
    import streamlit as st
    _secrets = dict(st.secrets)
except Exception:
    _secrets = {}


def _get_secret(name: str, default: str = "") -> str:
    if name in _secrets:
        return str(_secrets[name]).strip()
    val = os.getenv(name, default)
    return "" if val is None else str(val).strip()


ACCESS_ID = _get_secret("TUYA_ACCESS_ID", "")
ACCESS_SECRET = _get_secret("TUYA_ACCESS_SECRET", "")
API_ENDPOINT = _get_secret("TUYA_API_ENDPOINT", "https://openapi.tuyaeu.com")
HTTP_TIMEOUT = 15  # seconds


def _make_sign(client_id, secret, method, url, access_token: str = "", body: str = ""):
    t = str(int(time.time() * 1000))
    message = client_id + access_token + t
    string_to_sign = "\n".join(
        [
            method.upper(),
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "",
            url,
        ]
    )
    sign_str = message + string_to_sign
    sign = (
        hmac.new(secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256)
        .hexdigest()
        .upper()
    )
    return sign, t


_token_cache = {"value": None, "ts": 0.0, "ttl": 55.0}


def get_token() -> str:
    if not ACCESS_ID or not ACCESS_SECRET:
        raise RuntimeError("Tuya credentials missing (check TUYA_ACCESS_ID / TUYA_ACCESS_SECRET).")

    now = time.time()
    if _token_cache["value"] and (now - _token_cache["ts"] < _token_cache["ttl"]):
        return _token_cache["value"]

    path = "/v1.0/token?grant_type=1"
    sign, t = _make_sign(ACCESS_ID, ACCESS_SECRET, "GET", path)
    headers = {
        "client_id": ACCESS_ID,
        "sign": sign,
        "t": t,
        "sign_method": "HMAC-SHA256",
    }
    res = requests.get(API_ENDPOINT + path, headers=headers, timeout=HTTP_TIMEOUT)
    data = res.json()
    if not data.get("success"):
        raise RuntimeError(f"Failed to get Tuya token: {data}")

    _token_cache["value"] = data["result"]["access_token"]
    _token_cache["ts"] = now
    return _token_cache["value"]


def get_device_status(device_id: str, token: str) -> dict:
    path = f"/v1.0/devices/{device_id}/status"
    sign, t = _make_sign(ACCESS_ID, ACCESS_SECRET, "GET", path, token)
    headers = {
        "client_id": ACCESS_ID,
        "sign": sign,
        "t": t,
        "access_token": token,
        "sign_method": "HMAC-SHA256",
    }
    res = requests.get(API_ENDPOINT + path, headers=headers, timeout=HTTP_TIMEOUT)
    return res.json()


def control_device(device_id: str, token: str, code: str, value):
    path = f"/v1.0/devices/{device_id}/commands"
    body = json.dumps({"commands": [{"code": code, "value": value}]})
    sign, t = _make_sign(ACCESS_ID, ACCESS_SECRET, "POST", path, token, body)
    headers = {
        "client_id": ACCESS_ID,
        "sign": sign,
        "t": t,
        "access_token": token,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json",
    }
    res = requests.post(
        API_ENDPOINT + path, headers=headers, data=body, timeout=HTTP_TIMEOUT
    )
    return res.json()