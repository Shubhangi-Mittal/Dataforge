"""
10 — KPI Digest Bot
Computes KPIs from configured data, generates formatted digests,
and simulates Slack posting. Supports scheduling and custom KPIs.
"""

import json
import random
import math
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

# ── KPI definitions ────────────────────────────────────────
KPI_CONFIGS: dict[str, dict] = {}

DIGEST_HISTORY: list[dict] = []


def simulate_kpi_value(kpi_id: str) -> dict:
    """Generate realistic-looking KPI values with trends."""
    base_values = {
        "revenue": 45000, "dau": 12500, "churn": 3.2,
        "aov": 85.50, "error_rate": 0.8, "p95_latency": 230,
    }
    volatility = {
        "revenue": 0.15, "dau": 0.08, "churn": 0.2,
        "aov": 0.05, "error_rate": 0.3, "p95_latency": 0.12,
    }

    base = base_values.get(kpi_id, 100)
    vol = volatility.get(kpi_id, 0.1)

    today_value = base * (1 + random.gauss(0.02, vol))
    yesterday_value = base * (1 + random.gauss(0, vol))
    week_ago_value = base * (1 + random.gauss(-0.01, vol))

    day_change = ((today_value - yesterday_value) / yesterday_value) * 100
    week_change = ((today_value - week_ago_value) / week_ago_value) * 100

    config = KPI_CONFIGS.get(kpi_id, {})
    is_good_direction = (
        (day_change > 0 and config.get("trend_direction") == "up_is_good") or
        (day_change < 0 and config.get("trend_direction") == "down_is_good")
    )

    return {
        "kpi_id": kpi_id,
        "name": config.get("name", kpi_id),
        "current_value": round(today_value, 2),
        "yesterday_value": round(yesterday_value, 2),
        "week_ago_value": round(week_ago_value, 2),
        "day_change_pct": round(day_change, 2),
        "week_change_pct": round(week_change, 2),
        "trend_arrow": "↑" if day_change > 0 else "↓" if day_change < 0 else "→",
        "trend_status": "good" if is_good_direction else "bad" if not is_good_direction and abs(day_change) > 2 else "neutral",
        "unit": config.get("unit", ""),
    }


def generate_digest(kpi_ids: Optional[list] = None) -> dict:
    """Generate a full KPI digest."""
    ids = kpi_ids or list(KPI_CONFIGS.keys())
    now = datetime.utcnow()

    kpis = [simulate_kpi_value(kid) for kid in ids if kid in KPI_CONFIGS]

    # Generate Slack-style formatted message
    lines = [f"📊 *Daily KPI Digest* — {now.strftime('%B %d, %Y')}"]
    lines.append("─" * 36)
    for k in kpis:
        emoji = "🟢" if k["trend_status"] == "good" else "🔴" if k["trend_status"] == "bad" else "⚪"
        lines.append(f"{emoji} *{k['name']}*: {k['current_value']:,.2f} {k['unit']} {k['trend_arrow']} {k['day_change_pct']:+.1f}% vs yesterday")
    lines.append("─" * 36)

    good_count = sum(1 for k in kpis if k["trend_status"] == "good")
    bad_count = sum(1 for k in kpis if k["trend_status"] == "bad")
    if bad_count > good_count:
        lines.append("⚠️ _More KPIs trending negatively today. Worth investigating._")
    elif good_count > bad_count:
        lines.append("✅ _Most metrics trending positively. Good day!_")
    else:
        lines.append("📋 _Mixed signals today. Keep monitoring._")

    digest = {
        "generated_at": now.isoformat(),
        "kpi_count": len(kpis),
        "kpis": kpis,
        "slack_message": "\n".join(lines),
        "summary": {
            "trending_good": good_count,
            "trending_bad": bad_count,
            "neutral": len(kpis) - good_count - bad_count,
        },
    }

    DIGEST_HISTORY.append({"generated_at": now.isoformat(), "kpi_count": len(kpis)})
    return digest


# ── Endpoints ──────────────────────────────────────────────
@router.get("/kpis")
async def list_kpis():
    return {"count": len(KPI_CONFIGS), "kpis": list(KPI_CONFIGS.values())}


@router.post("/kpis")
async def add_kpi(kpi: dict):
    kid = kpi.get("id", "").strip()
    if not kid:
        raise HTTPException(400, "KPI needs an 'id'")
    KPI_CONFIGS[kid] = kpi
    return {"message": f"KPI '{kid}' added", "kpi": kpi}


@router.delete("/kpis/{kpi_id}")
async def remove_kpi(kpi_id: str):
    if kpi_id not in KPI_CONFIGS:
        raise HTTPException(404)
    del KPI_CONFIGS[kpi_id]
    return {"message": f"Deleted '{kpi_id}'"}


@router.get("/digest")
async def get_digest(kpis: Optional[str] = None):
    """Generate a KPI digest. Optionally filter by comma-separated KPI IDs."""
    kpi_ids = kpis.split(",") if kpis else None
    return generate_digest(kpi_ids)


@router.get("/digest/preview")
async def preview_slack_message(kpis: Optional[str] = None):
    """Preview the Slack-formatted message."""
    kpi_ids = kpis.split(",") if kpis else None
    digest = generate_digest(kpi_ids)
    return {"slack_message": digest["slack_message"]}


@router.get("/history")
async def digest_history():
    return {"count": len(DIGEST_HISTORY), "history": DIGEST_HISTORY[-20:]}


@router.get("/kpi/{kpi_id}/trend")
async def kpi_trend(kpi_id: str, days: int = Query(7, ge=1, le=30)):
    """Generate trend data for a specific KPI over N days."""
    if kpi_id not in KPI_CONFIGS:
        raise HTTPException(404)
    config = KPI_CONFIGS[kpi_id]
    base_values = {"revenue": 45000, "dau": 12500, "churn": 3.2, "aov": 85.50, "error_rate": 0.8, "p95_latency": 230}
    base = base_values.get(kpi_id, 100)

    trend = []
    now = datetime.utcnow()
    for i in range(days, 0, -1):
        dt = now - timedelta(days=i)
        val = base * (1 + random.gauss(0.01, 0.08)) + 2 * math.sin(i * 0.5)
        trend.append({"date": dt.strftime("%Y-%m-%d"), "value": round(val, 2)})

    return {"kpi_id": kpi_id, "name": config.get("name"), "days": days, "trend": trend}
