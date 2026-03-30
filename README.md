# ⚒ DataForge — Unified Data Engineering Microservices Platform

10 data-centric tools in one deployed platform. Built as a learning portfolio and practical toolkit for data analysts, business analysts, and data engineers.

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Vercel](https://img.shields.io/badge/Frontend-Vercel-black?logo=vercel&logoColor=white)
![Render](https://img.shields.io/badge/Backend-Render-46E3B7?logo=render&logoColor=white)
![Fly.io](https://img.shields.io/badge/Backend-Fly.io-8B5CF6?logo=flydotio&logoColor=white)

🔗 **Live Demo**: Frontend on Vercel · API Docs on deployed backend

---

## 🛠 The 10 Tools

| # | Tool | What It Does | Key Tech |
|---|------|-------------|----------|
| 01 | **CSV Schema Validator** | Validate files against schemas — types, nulls, ranges, uniqueness | Pandas, Pydantic |
| 02 | **SQL Query Analyzer** | Performance insights, complexity scoring, optimization tips | Regex, AST parsing |
| 03 | **Data Quality Monitor** | Completeness, outliers, distribution analysis, alerts | Statistics, NumPy |
| 04 | **REST-to-DB Sync** | Pull from REST APIs, map fields, sync to SQLite | SQLite, REST |
| 05 | **Auto EDA Reporter** | Instant EDA — stats, correlations, distributions, insights | Pandas, NumPy |
| 06 | **Lakehouse Organizer** | S3-style partitioning, Parquet conversion, metadata catalog | File management |
| 07 | **Metric Registry** | Business metric definitions — formulas, owners, lineage | CRUD, Lineage |
| 08 | **DAG Visualizer** | Pipeline dependency graphs, critical path, parallelization | Graph algorithms |
| 09 | **Log Anomaly Detector** | Z-score, IQR, moving average anomaly detection | Statistics |
| 10 | **KPI Digest Bot** | Slack-style daily digests with trends and comparisons | Scheduling |

---

## 🏗 Architecture

```
dataforge/
├── backend/                  # FastAPI (deploy on Render)
│   ├── app/
│   │   ├── main.py           # App entry + router registration
│   │   └── routers/          # 10 tool routers
│   │       ├── csv_validator.py
│   │       ├── sql_analyzer.py
│   │       ├── data_quality.py
│   │       ├── elt_sync.py
│   │       ├── eda_reporter.py
│   │       ├── lakehouse.py
│   │       ├── metric_registry.py
│   │       ├── dag_visualizer.py
│   │       ├── log_anomaly.py
│   │       └── kpi_digest.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── render.yaml
│
├── frontend/                 # Static HTML/CSS/JS (deploy on Vercel)
│   ├── index.html            # Card-based home page
│   ├── css/style.css         # Global stylesheet
│   ├── js/config.js          # API config + helpers
│   ├── pages/                # Individual tool pages
│   │   ├── csv-validator.html
│   │   ├── sql-analyzer.html
│   │   ├── data-quality.html
│   │   ├── elt-sync.html
│   │   ├── eda-reporter.html
│   │   ├── lakehouse.html
│   │   ├── metrics.html
│   │   ├── dag-visualizer.html
│   │   ├── log-anomaly.html
│   │   └── kpi-digest.html
│   └── vercel.json
│
└── README.md
```

---

## 🚀 Deployment (Free Tier)

### Backend → Render.com or Fly.io

1. Push `backend/` folder to a GitHub repo
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your repo, set root directory to `backend`
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Add environment variable `FRONTEND_URL=https://your-vercel-app.vercel.app`
7. Deploy — note your URL (e.g., `https://dataforge-api.onrender.com`)

### Backend → Fly.io

1. Install `flyctl` and sign in
2. Run `cd backend`
3. Run `fly launch --no-deploy`
4. Create a volume for SQLite persistence:
   `fly volumes create data --region <your-region> --size 1`
5. Set secrets:
   - `fly secrets set FRONTEND_URL=https://your-vercel-app.vercel.app`
   - `fly secrets set ALLOWED_ORIGINS=https://your-vercel-app.vercel.app`
6. Deploy with:
   `fly deploy`
7. Use the generated Fly URL as your frontend `API_BASE`

### Frontend → Vercel

1. Import the same repo into Vercel with root directory set to `frontend`
2. Go to [vercel.com](https://vercel.com) → Import Project
3. Set environment variable `API_BASE=https://your-render-app.onrender.com`
4. Set build command to `cd .. && npm run build`
5. Deploy — done!

### Local Development

```bash
# Terminal 1: Backend
cd backend
pip install -r requirements.txt
python -m app.main
# → http://localhost:8000/docs

# Terminal 2: Frontend
cd frontend
python -m http.server 3000
# → http://localhost:3000
```

---

## 📡 API Overview

All endpoints are under `https://your-render-app.onrender.com/api/`

| Tool | Endpoints |
|------|-----------|
| CSV Validator | `POST /validate/{schema}`, `POST /validate-auto`, `GET /schemas` |
| SQL Analyzer | `POST /analyze`, `POST /format` |
| Data Quality | `POST /check`, `POST /compare` |
| ELT Sync | `POST /sync/{config}`, `GET /configs`, `GET /preview/{config}` |
| EDA Reporter | `POST /analyze`, `POST /quick-stats` |
| Lakehouse | `POST /ingest`, `GET /catalog`, `GET /partitions`, `GET /stats` |
| Metrics | `GET /`, `POST /`, `GET /{id}/lineage` |
| DAG Visualizer | `GET /analyze/{pipeline}`, `GET /pipelines` |
| Log Anomaly | `POST /detect`, `POST /ingest`, `GET /generate-sample` |
| KPI Digest | `GET /digest`, `GET /kpi/{id}/trend`, `GET /kpis` |

Full interactive docs at `/docs` (Swagger UI).

---

## 📌 What I Learned

- **FastAPI router architecture** — organizing 10 services in one app with clean separation
- **Data validation from scratch** — type inference, schema enforcement, constraint checking
- **Statistical analysis** — z-scores, IQR, correlation matrices, distribution analysis
- **Graph algorithms** — topological sort, critical path analysis for DAG pipelines
- **ELT patterns** — API ingestion, field mapping, database sync workflows
- **Full-stack deployment** — free-tier Vercel + Render setup with CORS handling

---

## 📄 License

MIT — use it, fork it, learn from it.

---

Built by **Shubhangi Mittal** · [Portfolio](https://shubhangimittal.github.io) · [LinkedIn](https://linkedin.com/in/shubhangimittal22)
