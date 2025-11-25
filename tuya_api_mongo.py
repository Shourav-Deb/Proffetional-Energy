import os
from typing import Optional
from datetime import datetime, timezone

import pandas as pd
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError
from dotenv import load_dotenv


load_dotenv()

try:
    import streamlit as st
    _secrets = dict(st.secrets)
except Exception:
    _secrets = {}


def _strip_outer_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    return val


def _get_secret(name: str, default: str = "") -> str:
    if name in _secrets:
        val = str(_secrets[name])
        return _strip_outer_quotes(val)
    val = os.getenv(name, default)
    if val is None:
        return default
    return _strip_outer_quotes(str(val))


MONGODB_URI = _get_secret("MONGODB_URI", "")
MONGODB_DB = _get_secret("MONGODB_DB", "tuya_energy")

_client: Optional[MongoClient] = None


def get_client() -> Optional[MongoClient]:
    
    global _client
    if _client is None:
        if not MONGODB_URI:
            print("[Mongo] MONGODB_URI is empty. Check your .env or Streamlit secrets.")
            return None
        try:
            _client = MongoClient(MONGODB_URI, tls=True)
        except Exception as e:
            print(f"[Mongo] Error creating MongoClient: {e}")
            _client = None
    return _client


def _get_db(client: MongoClient):
    if client is None:
        return None
    try:
        db = client.get_default_database()
    except Exception:
        db = None
    if db is None:
        db = client[MONGODB_DB]
    return db


def _get_collection(device_id: str):
    client = get_client()
    if client is None:
        return None
    db = _get_db(client)
    coll = db[f"readings_{device_id}"]
    try:
        coll.create_index([("timestamp", ASCENDING)])
    except Exception:
        pass
    return coll


def insert_reading(device_id: str, doc: dict):
    coll = _get_collection(device_id)
    if coll is None:
        print("[Mongo] insert_reading: collection is None (no client/DB).")
        return
    doc = dict(doc)
    ts = doc.get("timestamp")
    if isinstance(ts, datetime) and ts.tzinfo is not None:
        doc["timestamp"] = ts.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        coll.insert_one(doc)
    except PyMongoError as e:
        print(f"[Mongo] insert_reading error: {e}")


def latest_docs(device_id: str, n: int = 50) -> pd.DataFrame:
    coll = _get_collection(device_id)
    if coll is None:
        return pd.DataFrame()
    try:
        docs = list(
            coll.find({}, sort=[("timestamp", DESCENDING)], limit=int(n))
        )
    except PyMongoError as e:
        print(f"[Mongo] latest_docs error: {e}")
        return pd.DataFrame()
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    if "_id" in df.columns:
        df.drop(columns=["_id"], inplace=True)
    return df.sort_values("timestamp")


def range_docs(device_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    coll = _get_collection(device_id)
    if coll is None:
        return pd.DataFrame()
    query = {"timestamp": {"$gte": start, "$lte": end}}
    try:
        docs = list(coll.find(query).sort("timestamp", ASCENDING))
    except PyMongoError as e:
        print(f"[Mongo] range_docs error: {e}")
        return pd.DataFrame()
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    if "_id" in df.columns:
        df.drop(columns=["_id"], inplace=True)
    return df
