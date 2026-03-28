"""
08 — Pipeline DAG Visualizer
Parses pipeline definitions and generates dependency graphs
with lineage, run-time estimation, and critical path analysis.
"""

import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ── Sample pipeline definitions ────────────────────────────
PIPELINES: dict[str, dict] = {}


def compute_dag_analysis(pipeline: dict) -> dict:
    nodes = pipeline["nodes"]

    # Build adjacency and in-degree
    adj = {n: [] for n in nodes}
    in_degree = {n: 0 for n in nodes}
    for n, data in nodes.items():
        for dep in data.get("depends_on", []):
            if dep in adj:
                adj[dep].append(n)
                in_degree[n] += 1

    # Topological sort (Kahn's)
    order = []
    queue = [n for n in nodes if in_degree[n] == 0]
    while queue:
        queue.sort()
        node = queue.pop(0)
        order.append(node)
        for child in adj[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Critical path (longest path by duration)
    earliest_start = {n: 0 for n in nodes}
    earliest_finish = {n: 0 for n in nodes}
    for n in order:
        for dep in nodes[n].get("depends_on", []):
            earliest_start[n] = max(earliest_start[n], earliest_finish[dep])
        earliest_finish[n] = earliest_start[n] + nodes[n].get("duration_min", 0)

    total_duration = max(earliest_finish.values()) if earliest_finish else 0

    # Find critical path (backtrack from end)
    end_nodes = [n for n in nodes if not adj[n]]
    critical_path = []
    if end_nodes:
        current = max(end_nodes, key=lambda x: earliest_finish[x])
        while current:
            critical_path.append(current)
            deps = nodes[current].get("depends_on", [])
            if not deps:
                break
            current = max(deps, key=lambda x: earliest_finish.get(x, 0))
        critical_path.reverse()

    # Build edges
    edges = []
    for n, data in nodes.items():
        for dep in data.get("depends_on", []):
            edges.append({"from": dep, "to": n})

    # Node details
    node_details = []
    for n in order:
        data = nodes[n]
        node_details.append({
            "id": n,
            "label": data.get("label", n),
            "type": data.get("type", "unknown"),
            "duration_min": data.get("duration_min", 0),
            "depends_on": data.get("depends_on", []),
            "earliest_start": earliest_start[n],
            "earliest_finish": earliest_finish[n],
            "is_critical": n in critical_path,
            "depth": len(data.get("depends_on", [])),
        })

    return {
        "pipeline": pipeline["name"],
        "description": pipeline.get("description", ""),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "execution_order": order,
        "critical_path": critical_path,
        "critical_path_duration_min": total_duration,
        "parallelizable_groups": _find_parallel_groups(nodes, order, earliest_start),
        "nodes": node_details,
        "edges": edges,
    }


def _find_parallel_groups(nodes, order, earliest_start):
    groups = {}
    for n in order:
        t = earliest_start[n]
        if t not in groups:
            groups[t] = []
        groups[t].append(n)
    return [{"start_time": t, "nodes": nds} for t, nds in sorted(groups.items())]


# ── Endpoints ──────────────────────────────────────────────
@router.get("/pipelines")
async def list_pipelines():
    return {"count": len(PIPELINES), "pipelines": [
        {"name": p["name"], "description": p.get("description", ""), "node_count": len(p["nodes"])}
        for p in PIPELINES.values()
    ]}


@router.get("/pipelines/{name}")
async def get_pipeline(name: str):
    if name not in PIPELINES:
        raise HTTPException(404, f"Pipeline '{name}' not found")
    return PIPELINES[name]


@router.post("/pipelines")
async def create_pipeline(pipeline: dict):
    name = pipeline.get("name", "").strip()
    if not name or not pipeline.get("nodes"):
        raise HTTPException(400, "Pipeline needs 'name' and 'nodes'")
    PIPELINES[name] = pipeline
    return {"message": f"Pipeline '{name}' created"}


@router.get("/analyze/{name}")
async def analyze_pipeline(name: str):
    if name not in PIPELINES:
        raise HTTPException(404, f"Pipeline '{name}' not found")
    return compute_dag_analysis(PIPELINES[name])


@router.delete("/pipelines/{name}")
async def delete_pipeline(name: str):
    if name not in PIPELINES:
        raise HTTPException(404)
    del PIPELINES[name]
    return {"message": f"Deleted '{name}'"}
