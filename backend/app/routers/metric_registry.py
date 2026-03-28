"""
07 — Metric Definition Registry
Centralized API for business metric definitions, formulas,
owners, data sources, and lineage tracking.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()

# ── In-memory metric store ─────────────────────────────────
METRICS: dict[str, dict] = {}


class MetricInput(BaseModel):
    id: str
    name: str
    description: str
    formula: str
    sql_definition: str = ""
    owner: str = ""
    data_source: str = ""
    warehouse: str = ""
    category: str = "General"
    granularity: str = "daily"
    unit: str = ""
    tags: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


# ── Endpoints ──────────────────────────────────────────────
@router.get("/")
async def list_metrics(category: Optional[str] = None, tag: Optional[str] = None,
                       search: Optional[str] = None):
    metrics = list(METRICS.values())
    if category:
        metrics = [m for m in metrics if m["category"].lower() == category.lower()]
    if tag:
        metrics = [m for m in metrics if tag.lower() in [t.lower() for t in m.get("tags", [])]]
    if search:
        s = search.lower()
        metrics = [m for m in metrics if s in m["name"].lower() or s in m["description"].lower()]
    return {"count": len(metrics), "metrics": metrics}


@router.get("/{metric_id}")
async def get_metric(metric_id: str):
    if metric_id not in METRICS:
        raise HTTPException(404, f"Metric '{metric_id}' not found")
    return METRICS[metric_id]


@router.post("/")
async def create_metric(metric: MetricInput):
    if metric.id in METRICS:
        raise HTTPException(409, f"Metric '{metric.id}' already exists")
    entry = metric.dict()
    entry["created_at"] = datetime.utcnow().isoformat()
    entry["updated_at"] = entry["created_at"]
    METRICS[metric.id] = entry
    return {"message": f"Metric '{metric.name}' created", "metric": entry}


@router.put("/{metric_id}")
async def update_metric(metric_id: str, metric: MetricInput):
    if metric_id not in METRICS:
        raise HTTPException(404, f"Metric '{metric_id}' not found")
    entry = metric.dict()
    entry["created_at"] = METRICS[metric_id].get("created_at", datetime.utcnow().isoformat())
    entry["updated_at"] = datetime.utcnow().isoformat()
    METRICS[metric_id] = entry
    return {"message": f"Metric '{metric.name}' updated", "metric": entry}


@router.delete("/{metric_id}")
async def delete_metric(metric_id: str):
    if metric_id not in METRICS:
        raise HTTPException(404, f"Metric '{metric_id}' not found")
    del METRICS[metric_id]
    return {"message": f"Metric '{metric_id}' deleted"}


@router.get("/categories/list")
async def list_categories():
    cats = {}
    for m in METRICS.values():
        cat = m.get("category", "General")
        cats[cat] = cats.get(cat, 0) + 1
    return {"categories": cats}


@router.get("/{metric_id}/lineage")
async def metric_lineage(metric_id: str):
    if metric_id not in METRICS:
        raise HTTPException(404, f"Metric '{metric_id}' not found")
    m = METRICS[metric_id]
    deps = m.get("dependencies", [])
    downstream = [mid for mid, mv in METRICS.items() if metric_id in mv.get("dependencies", []) and mid != metric_id]
    return {
        "metric": metric_id,
        "upstream_dependencies": deps,
        "downstream_dependents": downstream,
        "data_source": m.get("data_source"),
        "warehouse": m.get("warehouse"),
    }
