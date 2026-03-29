"""
07 — Metric Definition Registry
Centralized API for business metric definitions, formulas,
owners, data sources, and lineage tracking.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import storage

router = APIRouter()

# ── Persistent metric store ────────────────────────────────
METRICS: dict[str, dict] = storage.load_keyed_records("metrics")


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


def build_governance_summary() -> dict:
    metrics = list(METRICS.values())
    total = len(metrics)
    with_owner = sum(1 for m in metrics if m.get("owner"))
    with_sql = sum(1 for m in metrics if m.get("sql_definition"))
    with_tags = sum(1 for m in metrics if m.get("tags"))
    with_dependencies = sum(1 for m in metrics if m.get("dependencies"))

    gaps = []
    for metric in metrics:
        missing = []
        if not metric.get("owner"):
            missing.append("owner")
        if not metric.get("sql_definition"):
            missing.append("sql_definition")
        if not metric.get("tags"):
            missing.append("tags")
        if missing:
            gaps.append({"id": metric["id"], "name": metric["name"], "missing": missing})

    categories = {}
    for metric in metrics:
        category = metric.get("category", "General") or "General"
        categories[category] = categories.get(category, 0) + 1

    return {
        "total_metrics": total,
        "coverage": {
            "owner_pct": round((with_owner / total) * 100, 1) if total else 0,
            "sql_definition_pct": round((with_sql / total) * 100, 1) if total else 0,
            "tagged_pct": round((with_tags / total) * 100, 1) if total else 0,
            "dependency_mapped_pct": round((with_dependencies / total) * 100, 1) if total else 0,
        },
        "categories": categories,
        "gaps": gaps[:5],
    }


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


@router.get("/governance/summary")
async def governance_summary():
    return build_governance_summary()


@router.get("/categories/list")
async def list_categories():
    cats = {}
    for m in METRICS.values():
        cat = m.get("category", "General")
        cats[cat] = cats.get(cat, 0) + 1
    return {"categories": cats}


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
    storage.upsert_keyed_record("metrics", metric.id, entry)
    return {"message": f"Metric '{metric.name}' created", "metric": entry}


@router.put("/{metric_id}")
async def update_metric(metric_id: str, metric: MetricInput):
    if metric_id not in METRICS:
        raise HTTPException(404, f"Metric '{metric_id}' not found")
    entry = metric.dict()
    entry["created_at"] = METRICS[metric_id].get("created_at", datetime.utcnow().isoformat())
    entry["updated_at"] = datetime.utcnow().isoformat()
    METRICS[metric_id] = entry
    storage.upsert_keyed_record("metrics", metric_id, entry)
    return {"message": f"Metric '{metric.name}' updated", "metric": entry}


@router.delete("/{metric_id}")
async def delete_metric(metric_id: str):
    if metric_id not in METRICS:
        raise HTTPException(404, f"Metric '{metric_id}' not found")
    del METRICS[metric_id]
    storage.delete_keyed_record("metrics", metric_id)
    return {"message": f"Metric '{metric_id}' deleted"}


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
