"""
11 — Automation Center
Lightweight job orchestration for recurring DataForge workflows.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routers import kpi_digest, log_anomaly, sql_analyzer

router = APIRouter()

AUTOMATION_JOBS: dict[str, dict] = {}
AUTOMATION_HISTORY: list[dict] = []

VALID_JOB_TYPES = {"kpi_digest", "log_anomaly", "sql_analysis"}
VALID_FREQUENCIES = {"hourly", "daily", "weekly", "manual"}

DEFAULT_AUTOMATION_KPIS = {
    "revenue": {"id": "revenue", "name": "Revenue", "unit": "USD", "trend_direction": "up_is_good"},
    "churn": {"id": "churn", "name": "Churn Rate", "unit": "%", "trend_direction": "down_is_good"},
    "p95_latency": {"id": "p95_latency", "name": "P95 Latency", "unit": "ms", "trend_direction": "down_is_good"},
}


class AutomationJobInput(BaseModel):
    id: str
    name: str
    job_type: str
    frequency: str = "daily"
    enabled: bool = True
    config: dict = Field(default_factory=dict)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _compute_next_run(frequency: str, from_dt: Optional[datetime] = None) -> Optional[str]:
    if frequency == "manual":
        return None
    from_dt = from_dt or datetime.utcnow()
    delta_map = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
    }
    delta = delta_map.get(frequency)
    return (from_dt + delta).isoformat() if delta else None


def _build_job_record(job: AutomationJobInput) -> dict:
    if job.job_type not in VALID_JOB_TYPES:
        raise HTTPException(400, f"Unsupported job_type '{job.job_type}'")
    if job.frequency not in VALID_FREQUENCIES:
        raise HTTPException(400, f"Unsupported frequency '{job.frequency}'")

    created_at = _now_iso()
    return {
        "id": job.id,
        "name": job.name,
        "job_type": job.job_type,
        "frequency": job.frequency,
        "enabled": job.enabled,
        "config": job.config,
        "created_at": created_at,
        "updated_at": created_at,
        "last_run_at": None,
        "last_status": "never_run",
        "next_run_at": _compute_next_run(job.frequency) if job.enabled else None,
    }


def _execute_job(job: dict) -> dict:
    job_type = job["job_type"]
    config = job.get("config", {})

    if job_type == "kpi_digest":
        if not kpi_digest.KPI_CONFIGS:
            kpi_digest.KPI_CONFIGS.update(DEFAULT_AUTOMATION_KPIS)
        kpi_ids = config.get("kpi_ids")
        result = kpi_digest.generate_digest(kpi_ids)
        summary = f"Generated digest for {result['kpi_count']} KPI(s)"
        return {"result": result, "summary": summary}

    if job_type == "log_anomaly":
        values = config.get("values") or log_anomaly.generate_sample_data(40, anomaly_pct=10)
        method = config.get("method", "all")
        result = log_anomaly.detect_anomalies_zscore(values, log_anomaly.DETECTION_CONFIG["z_score_threshold"]) if method == "z_score" else None
        if method == "iqr":
            result = log_anomaly.detect_anomalies_iqr(values, log_anomaly.DETECTION_CONFIG["iqr_multiplier"])
        elif method == "moving_average":
            result = log_anomaly.detect_anomalies_moving_avg(values)
        elif method == "all":
            result = {
                "z_score": log_anomaly.detect_anomalies_zscore(values, log_anomaly.DETECTION_CONFIG["z_score_threshold"]),
                "iqr": log_anomaly.detect_anomalies_iqr(values, log_anomaly.DETECTION_CONFIG["iqr_multiplier"]),
                "moving_average": log_anomaly.detect_anomalies_moving_avg(values),
            }
        total = 0
        if isinstance(result, dict):
            total = sum(len(v) for v in result.values())
        else:
            total = len(result)
        summary = f"Detected {total} anomaly hits across {len(values)} values"
        return {"result": {"values": values, "method": method, "findings": result}, "summary": summary}

    if job_type == "sql_analysis":
        query = config.get("query", "")
        if not query:
            raise HTTPException(400, "SQL analysis jobs require config.query")
        dialect = config.get("dialect", "postgresql")
        result = sql_analyzer.analyze_query(query, dialect)
        summary = f"Analyzed {result['query_type']} query with {result['warning_count']} warning(s)"
        return {"result": result, "summary": summary}

    raise HTTPException(400, f"Unsupported job_type '{job_type}'")


def _record_history(job: dict, status: str, execution_summary: str, result: dict) -> dict:
    entry = {
        "job_id": job["id"],
        "job_name": job["name"],
        "job_type": job["job_type"],
        "status": status,
        "executed_at": _now_iso(),
        "summary": execution_summary,
        "result": result,
    }
    AUTOMATION_HISTORY.append(entry)
    return entry


@router.get("/jobs")
async def list_jobs():
    jobs = list(AUTOMATION_JOBS.values())
    return {"count": len(jobs), "jobs": jobs}


@router.post("/jobs")
async def create_job(job: AutomationJobInput):
    if job.id in AUTOMATION_JOBS:
        raise HTTPException(409, f"Job '{job.id}' already exists")
    record = _build_job_record(job)
    AUTOMATION_JOBS[job.id] = record
    return {"message": f"Job '{job.name}' created", "job": record}


@router.post("/jobs/{job_id}/toggle")
async def toggle_job(job_id: str):
    job = AUTOMATION_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    job["enabled"] = not job["enabled"]
    job["updated_at"] = _now_iso()
    job["next_run_at"] = _compute_next_run(job["frequency"]) if job["enabled"] and job["frequency"] != "manual" else None
    return {"message": f"Job '{job['name']}' {'enabled' if job['enabled'] else 'paused'}", "job": job}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    if job_id not in AUTOMATION_JOBS:
        raise HTTPException(404, f"Job '{job_id}' not found")
    removed = AUTOMATION_JOBS.pop(job_id)
    return {"message": f"Deleted '{removed['name']}'"}


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str):
    job = AUTOMATION_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    started_at = datetime.utcnow()
    execution = _execute_job(job)
    job["last_run_at"] = started_at.isoformat()
    job["last_status"] = "success"
    job["updated_at"] = _now_iso()
    job["next_run_at"] = _compute_next_run(job["frequency"], started_at) if job["enabled"] and job["frequency"] != "manual" else None
    history_entry = _record_history(job, "success", execution["summary"], execution["result"])
    return {"message": f"Ran '{job['name']}'", "job": job, "execution": history_entry}


@router.post("/jobs/run-due")
async def run_due_jobs():
    now = datetime.utcnow()
    executed = []
    for job in AUTOMATION_JOBS.values():
        if not job["enabled"] or not job.get("next_run_at"):
            continue
        next_run = datetime.fromisoformat(job["next_run_at"])
        if next_run <= now:
            execution = _execute_job(job)
            job["last_run_at"] = now.isoformat()
            job["last_status"] = "success"
            job["updated_at"] = _now_iso()
            job["next_run_at"] = _compute_next_run(job["frequency"], now)
            executed.append(_record_history(job, "success", execution["summary"], execution["result"]))
    return {"executed_count": len(executed), "executions": executed}


@router.get("/history")
async def list_history(limit: int = 20):
    return {"count": len(AUTOMATION_HISTORY), "history": AUTOMATION_HISTORY[-limit:]}


@router.get("/summary")
async def automation_summary():
    jobs = list(AUTOMATION_JOBS.values())
    active = sum(1 for job in jobs if job["enabled"])
    paused = sum(1 for job in jobs if not job["enabled"])
    type_breakdown = {}
    for job in jobs:
        type_breakdown[job["job_type"]] = type_breakdown.get(job["job_type"], 0) + 1
    return {
        "total_jobs": len(jobs),
        "active_jobs": active,
        "paused_jobs": paused,
        "history_entries": len(AUTOMATION_HISTORY),
        "job_types": type_breakdown,
    }
