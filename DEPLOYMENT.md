Deployment notes — DataForge

Goal
- Deploy frontend to Vercel (static) and backend to Fly.io (Python web service).

Frontend (Vercel)
- The frontend reads the backend URL at runtime from `window.__API_BASE__`.
- Recommended Vercel setup:
  1. Set the project root to `frontend`.
  2. Add an `API_BASE` environment variable in Vercel with your Fly backend URL, for example `https://dataforge-api.fly.dev`.
  3. Add the build command `cd .. && npm run build`.
  4. Keep the output directory as `.` because the built site remains in `frontend/`.
- `npm run build` writes `frontend/env.js` using `scripts/generate-env.js`, so the deployed frontend knows where the backend lives.
- The API Docs button is now populated from `window.__API_BASE__`; there is no hardcoded `/docs` rewrite to keep in sync.

Backend (Fly.io)
- `backend/fly.toml` is included for a container-based Fly deployment.
- The app expects a persistent volume mounted at `/data` and stores SQLite at `DATAFORGE_DB_PATH=/data/dataforge_platform.db`.
- Recommended steps:
  1. Install `flyctl` and sign in.
  2. Run `cd backend`.
  3. Run `fly launch --no-deploy` and keep the generated app name or update `app` in `fly.toml`.
  4. Create the persistent volume: `fly volumes create data --region <your-region> --size 1`.
  5. Set secrets:
     - `fly secrets set FRONTEND_URL=https://your-vercel-app.vercel.app`
     - `fly secrets set ALLOWED_ORIGINS=https://your-vercel-app.vercel.app`
  6. Deploy with `fly deploy`.
- The included `fly.toml` uses `shared-cpu-1x` with `1024MB` RAM, which is a better fit for pandas-based uploads than smaller free-tier instances.

Files added/changed
- `frontend/env.js` — runtime loader that sets `window.__API_BASE__` for local and production fallbacks.
- `frontend/favicon.svg` and `frontend/favicon.ico` — favicons to avoid 404s.
- `backend/app/routers/csv_validator.py` — robust CSV parsing, encoding sniffing, binary detection, and helpful 400 errors.
- `backend/app/main.py` — explicit CORS and development exception handler.
- `backend/app/storage.py` — database path can now be overridden with `DATAFORGE_DB_PATH`, which is used by Fly volumes.
- `backend/fly.toml` — Fly.io app config with a persistent `/data` mount.
- `backend/.dockerignore` — smaller Fly Docker build context.
- `frontend/js/config.js` — frontend requests now fail clearly when `API_BASE` was not configured during deployment.
- `frontend/vercel.json` — security headers only, plus `env.js` is marked `no-store` so API host changes propagate cleanly.

Quick local test
1. Start backend:
   cd backend
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
2. Serve frontend:
   cd frontend
   python -m http.server 3000 --bind 127.0.0.1
3. Open http://127.0.0.1:3000 and try the tools.

Notes
- For production, configure `FRONTEND_URL` or `ALLOWED_ORIGINS` before exposing the backend publicly.
- Before the first Vercel deploy, verify the `API_BASE` env var points to the live Fly service, not localhost.
