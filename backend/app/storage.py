"""
Shared SQLite persistence layer for DataForge.
"""

import json
import math
import os
import sqlite3
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


DB_PATH = Path(os.getenv("DATAFORGE_DB_PATH", Path(__file__).resolve().parents[1] / "dataforge_platform.db"))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def sanitize_for_json(obj: Any) -> Any:
    if obj is None:
        return None
    if obj is pd.NA:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()
    if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
        return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
    if isinstance(obj, (np.datetime64,)):
        return str(obj)
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(obj, np.generic):
        return sanitize_for_json(obj.item())
    if isinstance(obj, np.ndarray):
        return [sanitize_for_json(item) for item in obj.tolist()]
    if isinstance(obj, pd.Series):
        return [sanitize_for_json(item) for item in obj.tolist()]
    if isinstance(obj, pd.Index):
        return [sanitize_for_json(item) for item in obj.tolist()]
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(value) for value in obj]
    if isinstance(obj, pd.DataFrame):
        return sanitize_for_json(obj.to_dict(orient="records"))
    return obj


def _json_dumps(data: Any) -> str:
    return json.dumps(sanitize_for_json(data))


def init_db() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kpi_configs (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS automation_jobs (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS automation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kpi_digest_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS saved_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            report_type TEXT NOT NULL,
            name TEXT NOT NULL,
            data TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def load_keyed_records(table: str) -> dict[str, dict]:
    conn = get_connection()
    rows = conn.execute(f"SELECT id, data FROM {table}").fetchall()
    conn.close()
    records = {}
    for row in rows:
        records[row["id"]] = json.loads(row["data"])
    return records


def upsert_keyed_record(table: str, key: str, data: dict) -> None:
    conn = get_connection()
    conn.execute(
        f"INSERT INTO {table} (id, data) VALUES (?, ?) "
        f"ON CONFLICT(id) DO UPDATE SET data=excluded.data",
        (key, _json_dumps(data)),
    )
    conn.commit()
    conn.close()


def delete_keyed_record(table: str, key: str) -> None:
    conn = get_connection()
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (key,))
    conn.commit()
    conn.close()


def append_history(table: str, data: dict, created_at: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        f"INSERT INTO {table} (created_at, data) VALUES (?, ?)",
        (created_at, _json_dumps(data)),
    )
    conn.commit()
    row_id = int(cursor.lastrowid)
    conn.close()
    return row_id


def list_history(table: str, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        f"SELECT id, created_at, data FROM {table} ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        data = json.loads(row["data"])
        data.setdefault("id", row["id"])
        data.setdefault("created_at", row["created_at"])
        results.append(data)
    return results


def create_notification(payload: dict, created_at: str) -> dict:
    record = {"created_at": created_at, "read": False, **payload}
    record_id = append_history("notifications", record, created_at)
    record["id"] = record_id
    return record


def list_notifications(limit: int = 50, unread_only: bool = False) -> list[dict]:
    conn = get_connection()
    if unread_only:
        rows = conn.execute(
            "SELECT id, created_at, read, data FROM notifications WHERE read = 0 ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, created_at, read, data FROM notifications ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    notifications = []
    for row in rows:
        data = json.loads(row["data"])
        data["id"] = row["id"]
        data["created_at"] = row["created_at"]
        data["read"] = bool(row["read"])
        notifications.append(data)
    return notifications


def mark_notification_read(notification_id: int) -> Optional[dict]:
    conn = get_connection()
    conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))
    row = conn.execute(
        "SELECT id, created_at, read, data FROM notifications WHERE id = ?",
        (notification_id,),
    ).fetchone()
    conn.commit()
    conn.close()
    if not row:
        return None
    data = json.loads(row["data"])
    data["id"] = row["id"]
    data["created_at"] = row["created_at"]
    data["read"] = bool(row["read"])
    return data


def save_report(report_type: str, name: str, payload: dict, created_at: str) -> dict:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO saved_reports (created_at, report_type, name, data) VALUES (?, ?, ?, ?)",
        (created_at, report_type, name, _json_dumps(payload)),
    )
    conn.commit()
    report_id = int(cursor.lastrowid)
    conn.close()
    return {"id": report_id, "created_at": created_at, "report_type": report_type, "name": name, "data": payload}


def list_reports(report_type: Optional[str] = None, limit: int = 50) -> list[dict]:
    conn = get_connection()
    if report_type:
        rows = conn.execute(
            "SELECT id, created_at, report_type, name, data FROM saved_reports WHERE report_type = ? ORDER BY id DESC LIMIT ?",
            (report_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, created_at, report_type, name, data FROM saved_reports ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    reports = []
    for row in rows:
        reports.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "report_type": row["report_type"],
            "name": row["name"],
            "data": json.loads(row["data"]),
        })
    return reports


def get_report(report_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, created_at, report_type, name, data FROM saved_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "report_type": row["report_type"],
        "name": row["name"],
        "data": json.loads(row["data"]),
    }


init_db()
