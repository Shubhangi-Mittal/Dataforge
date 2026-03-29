"""
02 — SQL Query Analyzer
Parses SQL queries and provides performance insights, complexity scoring,
join analysis, and optimization recommendations.
"""

import re
import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class SQLInput(BaseModel):
    query: str
    dialect: str = "postgresql"


class OptimizationRule:
    def __init__(self, name: str, pattern: str, severity: str, message: str, suggestion: str):
        self.name = name
        self.pattern = pattern
        self.severity = severity
        self.message = message
        self.suggestion = suggestion


RULES = [
    OptimizationRule("select_star", r"\bSELECT\s+\*", "warning",
                     "SELECT * fetches all columns, increasing I/O",
                     "List only the columns you need"),
    OptimizationRule("no_where", r"(?i)^SELECT\b(?:(?!\bWHERE\b).)*$", "warning",
                     "Query has no WHERE clause — full table scan likely",
                     "Add a WHERE clause to filter rows"),
    OptimizationRule("leading_wildcard", r"LIKE\s+['\"]%", "warning",
                     "Leading wildcard in LIKE prevents index usage",
                     "Use full-text search or restructure the filter"),
    OptimizationRule("or_in_where", r"WHERE\s+.*?\bOR\b", "info",
                     "OR conditions may prevent index usage",
                     "Consider using UNION or IN(...) instead"),
    OptimizationRule("not_in", r"\bNOT\s+IN\b", "info",
                     "NOT IN can behave unexpectedly with NULLs",
                     "Use NOT EXISTS or LEFT JOIN ... IS NULL"),
    OptimizationRule("implicit_cartesian", r"(?i)FROM\s+\w+\s*,\s*\w+(?!\s+WHERE)", "error",
                     "Implicit join (comma syntax) risks cartesian product",
                     "Use explicit JOIN ... ON syntax"),
    OptimizationRule("order_without_limit", r"(?i)ORDER\s+BY\b(?:(?!\bLIMIT\b).)*$", "info",
                     "ORDER BY without LIMIT sorts entire result set",
                     "Add LIMIT if you don't need all rows"),
    OptimizationRule("nested_subquery", r"(?i)SELECT.*\(\s*SELECT", "info",
                     "Nested subquery detected — may impact performance",
                     "Consider using CTEs or JOINs for readability"),
    OptimizationRule("distinct_usage", r"\bDISTINCT\b", "info",
                     "DISTINCT forces deduplication pass",
                     "Check if the query logic already guarantees uniqueness"),
    OptimizationRule("function_in_where", r"(?i)WHERE\s+\w+\s*\(", "warning",
                     "Function call in WHERE may prevent index usage",
                     "Pre-compute or use functional indexes"),
]


def parse_tables(query: str) -> list[str]:
    tables = set()
    for m in re.finditer(r'(?i)\bFROM\s+([\w.]+)', query):
        tables.add(m.group(1))
    for m in re.finditer(r'(?i)\bJOIN\s+([\w.]+)', query):
        tables.add(m.group(1))
    return sorted(tables)


def parse_joins(query: str) -> list[dict]:
    joins = []
    for m in re.finditer(r'(?i)(INNER|LEFT|RIGHT|FULL|CROSS)?\s*JOIN\s+([\w.]+)\s+(?:AS\s+)?(\w+)?\s*ON\s+(.+?)(?=(?:INNER|LEFT|RIGHT|FULL|CROSS)?\s*JOIN|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|$)', query):
        joins.append({
            "type": (m.group(1) or "INNER").upper(),
            "table": m.group(2),
            "alias": m.group(3) or m.group(2),
            "condition": m.group(4).strip().rstrip(";"),
        })
    return joins


def parse_columns(query: str) -> list[str]:
    m = re.match(r'(?i)SELECT\s+(.*?)\s+FROM\b', query, re.DOTALL)
    if not m:
        return []
    raw = m.group(1)
    if raw.strip() == "*":
        return ["*"]
    cols = [c.strip().split()[-1].split(".")[-1] for c in raw.split(",")]
    return cols


def calculate_complexity(query: str, joins: list, tables: list) -> dict:
    score = 1
    factors = []
    if len(tables) > 1:
        score += len(tables) - 1
        factors.append(f"{len(tables)} tables")
    if joins:
        score += len(joins) * 2
        factors.append(f"{len(joins)} joins")
    subq = len(re.findall(r'(?i)\(\s*SELECT', query))
    if subq:
        score += subq * 3
        factors.append(f"{subq} subqueries")
    aggs = len(re.findall(r'(?i)\b(COUNT|SUM|AVG|MIN|MAX|GROUP BY|HAVING)\b', query))
    if aggs:
        score += aggs
        factors.append(f"{aggs} aggregation ops")
    windows = len(re.findall(r'(?i)\bOVER\s*\(', query))
    if windows:
        score += windows * 2
        factors.append(f"{windows} window functions")
    ctes = len(re.findall(r'(?i)\bWITH\b', query))
    if ctes:
        score += ctes
        factors.append(f"{ctes} CTEs")

    level = "low" if score <= 3 else "medium" if score <= 8 else "high" if score <= 15 else "very high"
    return {"score": score, "level": level, "factors": factors}


def suggest_indexes(query: str, tables: list) -> list[dict]:
    suggestions = []
    for m in re.finditer(r'(?i)WHERE\s+(?:.*?\b)?(\w+)\.?(\w+)\s*[=<>]', query):
        tbl = m.group(1) if "." in m.group(0) else tables[0] if tables else "unknown"
        col = m.group(2)
        suggestions.append({"table": tbl, "column": col, "reason": "Used in WHERE clause filter"})
    for m in re.finditer(r'(?i)ORDER\s+BY\s+(?:(\w+)\.)?(\w+)', query):
        tbl = m.group(1) or (tables[0] if tables else "unknown")
        suggestions.append({"table": tbl, "column": m.group(2), "reason": "Used in ORDER BY"})
    for m in re.finditer(r'(?i)GROUP\s+BY\s+(?:(\w+)\.)?(\w+)', query):
        tbl = m.group(1) or (tables[0] if tables else "unknown")
        suggestions.append({"table": tbl, "column": m.group(2), "reason": "Used in GROUP BY"})
    seen = set()
    deduped = []
    for s in suggestions:
        key = f"{s['table']}.{s['column']}"
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped


def build_clause_breakdown(query: str) -> list[dict]:
    clauses = [
        ("WITH", r"(?i)\bWITH\b", "Common table expressions used to stage intermediate logic"),
        ("SELECT", r"(?i)\bSELECT\b", "Projected columns returned by the query"),
        ("FROM", r"(?i)\bFROM\b", "Primary source tables"),
        ("WHERE", r"(?i)\bWHERE\b", "Row-level filtering"),
        ("GROUP BY", r"(?i)\bGROUP\s+BY\b", "Aggregation grouping"),
        ("HAVING", r"(?i)\bHAVING\b", "Post-aggregation filtering"),
        ("ORDER BY", r"(?i)\bORDER\s+BY\b", "Sorting result rows"),
        ("LIMIT", r"(?i)\bLIMIT\b", "Caps output row count"),
    ]
    return [
        {"clause": name, "present": bool(re.search(pattern, query)), "detail": detail}
        for name, pattern, detail in clauses
    ]


def build_summary(query_type: str, complexity: dict, warnings: list[dict], joins: list[dict]) -> dict:
    severity_rank = {"info": 1, "warning": 2, "error": 3, "critical": 4}
    highest = "info"
    if warnings:
        highest = max(warnings, key=lambda w: severity_rank.get(w["severity"], 1))["severity"]

    if highest in {"error", "critical"} or complexity["level"] in {"high", "very high"}:
        risk = "high"
    elif highest == "warning" or complexity["level"] == "medium":
        risk = "medium"
    else:
        risk = "low"

    headline_bits = [query_type.title(), complexity["level"] + " complexity"]
    if joins:
        headline_bits.append(f"{len(joins)} join{'s' if len(joins) != 1 else ''}")

    actions = []
    for warning in warnings[:3]:
        actions.append(warning["suggestion"])
    if not actions:
        actions.append("Query shape looks healthy; validate against real execution plans before shipping.")

    return {
        "headline": " | ".join(headline_bits),
        "risk_level": risk,
        "highest_severity": highest,
        "key_actions": actions,
    }


def build_optimization_checklist(query: str, warnings: list[dict], indexes: list[dict]) -> list[dict]:
    warning_rules = {w["rule"] for w in warnings}
    checklist = [
        {
            "label": "Projection is selective",
            "status": "warning" if "select_star" in warning_rules else "pass",
            "detail": "Avoid SELECT * so scans stay narrow and predictable.",
        },
        {
            "label": "Filter strategy is bounded",
            "status": "warning" if "no_where" in warning_rules else "pass",
            "detail": "Queries with filters usually cost less than full-table scans.",
        },
        {
            "label": "Sorting is scoped",
            "status": "warning" if "order_without_limit" in warning_rules else "pass",
            "detail": "Pair ORDER BY with LIMIT when you only need the top rows.",
        },
        {
            "label": "Index opportunities captured",
            "status": "pass" if indexes else "info",
            "detail": "Suggested indexes are derived from WHERE, GROUP BY, and ORDER BY usage.",
        },
    ]
    if re.search(r"(?i)\bJOIN\b", query):
        checklist.append({
            "label": "Join conditions are explicit",
            "status": "error" if "implicit_cartesian" in warning_rules else "pass",
            "detail": "Explicit JOIN ... ON clauses keep relationships readable and safer.",
        })
    return checklist


def analyze_query(query: str, dialect: str = "postgresql") -> dict:
    q = query.strip().rstrip(";")
    if not q:
        raise ValueError("Empty query")

    tables = parse_tables(q)
    joins = parse_joins(q)
    columns = parse_columns(q)
    complexity = calculate_complexity(q, joins, tables)
    indexes = suggest_indexes(q, tables)
    clause_breakdown = build_clause_breakdown(q)

    warnings = []
    for rule in RULES:
        if re.search(rule.pattern, q, re.IGNORECASE | re.DOTALL):
            warnings.append({
                "rule": rule.name,
                "severity": rule.severity,
                "message": rule.message,
                "suggestion": rule.suggestion,
            })

    q_type = "UNKNOWN"
    for t in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"]:
        if re.match(rf'(?i)\b{t}\b', q):
            q_type = t
            break

    summary = build_summary(q_type, complexity, warnings, joins)
    checklist = build_optimization_checklist(q, warnings, indexes)

    return {
        "query_type": q_type,
        "tables": tables,
        "columns": columns,
        "joins": joins,
        "complexity": complexity,
        "summary": summary,
        "clause_breakdown": clause_breakdown,
        "optimization_checklist": checklist,
        "index_suggestions": indexes,
        "warnings": warnings,
        "warning_count": len(warnings),
        "dialect": dialect,
    }


# ── Endpoints ──────────────────────────────────────────────
@router.post("/analyze")
async def analyze(input: SQLInput):
    try:
        result = analyze_query(input.query, input.dialect)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/format")
async def format_sql(input: SQLInput):
    """Basic SQL formatting."""
    q = input.query.strip()
    keywords = ["SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN",
                "INNER JOIN", "ON", "GROUP BY", "ORDER BY", "HAVING", "LIMIT",
                "UNION", "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM",
                "CREATE TABLE", "ALTER TABLE", "WITH"]
    formatted = q
    for kw in sorted(keywords, key=len, reverse=True):
        formatted = re.sub(rf'(?i)\b{kw}\b', f'\n{kw.upper()}', formatted)
    formatted = formatted.strip()
    return {"original": q, "formatted": formatted}
