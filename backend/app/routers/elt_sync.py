"""
04 — REST-to-Database Sync
Configurable ELT microservice that pulls from REST APIs,
transforms data, and syncs to a SQLite database.
"""

import json
import sqlite3
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

DB_PATH = "dataforge_elt.db"

# ── In-memory job store ────────────────────────────────────
SYNC_CONFIGS: dict[str, dict] = {}

SYNC_HISTORY: list[dict] = []


class SyncConfig(BaseModel):
    name: str
    source_url: str
    method: str = "GET"
    headers: Optional[dict] = None
    table_name: str
    field_mapping: dict
    schedule: str = "manual"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS _sync_log (id INTEGER PRIMARY KEY, config_name TEXT, status TEXT, rows_synced INTEGER, started_at TEXT, finished_at TEXT, error TEXT)")
    conn.commit()
    conn.close()


init_db()


def simulate_sync(config: dict) -> dict:
    """Simulate a sync job (actual HTTP calls would happen in production)."""
    started = datetime.utcnow().isoformat()
    mapping = config["field_mapping"]

    # Generate sample data based on mapping
    sample_rows = []
    for i in range(1, 11):
        row = {}
        for src_field, target_def in mapping.items():
            target_col = target_def["target"]
            col_type = target_def.get("type", "TEXT")
            if col_type == "INTEGER":
                row[target_col] = i
            else:
                row[target_col] = f"sample_{src_field}_{i}"
        sample_rows.append(row)

    # Write to SQLite
    conn = sqlite3.connect(DB_PATH)
    table = config["table_name"]
    cols_def = ", ".join(f"{v['target']} {v.get('type', 'TEXT')}" for v in mapping.values())
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols_def})")
    conn.execute(f"DELETE FROM {table}")

    for row in sample_rows:
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(row.values()))

    conn.commit()
    finished = datetime.utcnow().isoformat()

    log_entry = {
        "config_name": config["name"],
        "status": "success",
        "rows_synced": len(sample_rows),
        "started_at": started,
        "finished_at": finished,
        "error": None,
    }
    conn.execute("INSERT INTO _sync_log (config_name, status, rows_synced, started_at, finished_at, error) VALUES (?, ?, ?, ?, ?, ?)",
                 (log_entry["config_name"], log_entry["status"], log_entry["rows_synced"], log_entry["started_at"], log_entry["finished_at"], log_entry["error"]))
    conn.commit()
    conn.close()

    SYNC_HISTORY.append(log_entry)
    return log_entry


# ── Endpoints ──────────────────────────────────────────────
@router.get("/configs")
async def list_configs():
    return {"count": len(SYNC_CONFIGS), "configs": list(SYNC_CONFIGS.values())}


@router.get("/configs/{name}")
async def get_config(name: str):
    if name not in SYNC_CONFIGS:
        raise HTTPException(404, f"Config '{name}' not found")
    return SYNC_CONFIGS[name]


@router.post("/configs")
async def create_config(config: SyncConfig):
    SYNC_CONFIGS[config.name] = config.dict()
    SYNC_CONFIGS[config.name]["created_at"] = datetime.utcnow().isoformat()
    return {"message": f"Config '{config.name}' created", "config": SYNC_CONFIGS[config.name]}


@router.post("/sync/{config_name}")
async def trigger_sync(config_name: str):
    """Trigger a sync job for a given config."""
    if config_name not in SYNC_CONFIGS:
        raise HTTPException(404, f"Config '{config_name}' not found")
    try:
        result = simulate_sync(SYNC_CONFIGS[config_name])
        return {"message": "Sync completed", "result": result}
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


@router.get("/history")
async def sync_history():
    return {"count": len(SYNC_HISTORY), "history": SYNC_HISTORY[-20:]}


@router.get("/preview/{config_name}")
async def preview_data(config_name: str, limit: int = 10):
    """Preview synced data from the database."""
    if config_name not in SYNC_CONFIGS:
        raise HTTPException(404, f"Config '{config_name}' not found")
    table = SYNC_CONFIGS[config_name]["table_name"]
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM {table} LIMIT ?", (limit,)).fetchall()
        conn.close()
        return {"table": table, "count": len(rows), "rows": [dict(r) for r in rows]}
    except sqlite3.OperationalError:
        return {"table": table, "count": 0, "rows": [], "note": "Table not yet created. Run a sync first."}
