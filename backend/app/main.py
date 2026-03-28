"""
DataForge — Unified Data Engineering Microservices Platform
10 data-centric tools in one FastAPI backend.
"""

import os
import json
import math
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn


def _sanitize(obj):
    """Recursively replace NaN/Inf with None for valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class NumpyEncoder(json.JSONEncoder):
    """Handle numpy types that aren't JSON serializable."""
    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        if isinstance(obj, np.ndarray):
            return _sanitize(obj.tolist())
        return super().default(obj)


class NumpySafeResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(_sanitize(content), cls=NumpyEncoder).encode("utf-8")

from app.routers import (
    csv_validator,
    sql_analyzer,
    data_quality,
    elt_sync,
    eda_reporter,
    lakehouse,
    metric_registry,
    dag_visualizer,
    log_anomaly,
    kpi_digest,
)

app = FastAPI(
    title="DataForge API",
    description="10 data-centric microservices in one platform. "
                "Schema validation, SQL analysis, EDA reports, data quality monitoring, and more.",
    version="1.0.0",
    docs_url="/docs",
    default_response_class=NumpySafeResponse,
)

def _build_allowed_origins() -> list[str]:
    """Compute allowed CORS origins from env while keeping safe local defaults."""
    configured = os.getenv("ALLOWED_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]

    frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if frontend_url:
        origins.append(frontend_url)

    if os.getenv("ENV", "development") != "production":
        origins.extend(["http://localhost:3000", "http://127.0.0.1:3000"])

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(origins))


allow_origins = _build_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add a development-only exception handler so clients receive JSON traces while
# debugging locally. This is disabled when ENV=production.
if os.getenv('ENV', 'development') != 'production':
    @app.exception_handler(Exception)
    async def _dev_exception_handler(request: Request, exc: Exception):
        import traceback
        tb = traceback.format_exc()
        return JSONResponse({"detail": str(exc), "trace": tb}, status_code=500,
                            headers={"Access-Control-Allow-Origin": "*"})

# ── Register all tool routers ──────────────────────────────
app.include_router(csv_validator.router, prefix="/api/csv-validator", tags=["01 — CSV Schema Validator"])
app.include_router(sql_analyzer.router, prefix="/api/sql-analyzer", tags=["02 — SQL Query Analyzer"])
app.include_router(data_quality.router, prefix="/api/data-quality", tags=["03 — Data Quality Monitor"])
app.include_router(elt_sync.router, prefix="/api/elt-sync", tags=["04 — REST-to-DB Sync"])
app.include_router(eda_reporter.router, prefix="/api/eda-reporter", tags=["05 — Auto EDA Reporter"])
app.include_router(lakehouse.router, prefix="/api/lakehouse", tags=["06 — Lakehouse Organizer"])
app.include_router(metric_registry.router, prefix="/api/metrics", tags=["07 — Metric Registry"])
app.include_router(dag_visualizer.router, prefix="/api/dag-visualizer", tags=["08 — DAG Visualizer"])
app.include_router(log_anomaly.router, prefix="/api/log-anomaly", tags=["09 — Log Anomaly Detector"])
app.include_router(kpi_digest.router, prefix="/api/kpi-digest", tags=["10 — KPI Digest Bot"])


@app.get("/", tags=["System"])
async def root():
    return {
        "name": "DataForge",
        "version": "1.0.0",
        "tools": [
            {"id": "csv-validator", "name": "CSV Schema Validator", "status": "active"},
            {"id": "sql-analyzer", "name": "SQL Query Analyzer", "status": "active"},
            {"id": "data-quality", "name": "Data Quality Monitor", "status": "active"},
            {"id": "elt-sync", "name": "REST-to-DB Sync", "status": "active"},
            {"id": "eda-reporter", "name": "Auto EDA Reporter", "status": "active"},
            {"id": "lakehouse", "name": "Lakehouse Organizer", "status": "active"},
            {"id": "metrics", "name": "Metric Registry", "status": "active"},
            {"id": "dag-visualizer", "name": "DAG Visualizer", "status": "active"},
            {"id": "log-anomaly", "name": "Log Anomaly Detector", "status": "active"},
            {"id": "kpi-digest", "name": "KPI Digest Bot", "status": "active"},
        ],
    }


@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy", "service": "dataforge", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
