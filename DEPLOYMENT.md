Deployment notes — DataForge

Goal
- Deploy frontend to Vercel (static) and backend to Render (Python web service).

Frontend (Vercel)
- The frontend reads the backend URL at runtime from `window.__API_BASE__`.
- Recommended Vercel setup:
  1. Set the project root to `frontend`.
  2. Add an `API_BASE` environment variable in Vercel with your Render backend URL, for example `https://dataforge-api.onrender.com`.
  3. Add the build command `cd .. && npm run build`.
  4. Keep the output directory as `.` because the built site remains in `frontend/`.
- `npm run build` writes `frontend/env.js` using `scripts/generate-env.js`, so the deployed frontend knows where the backend lives.
- The API Docs button is now populated from `window.__API_BASE__`; there is no hardcoded `/docs` rewrite to keep in sync.

Backend (Render)
- `backend/render.yaml` is configured to run the app using `uvicorn` and install `requirements.txt`.
- Set `FRONTEND_URL` to your Vercel production URL, for example `https://dataforge.vercel.app`.
- If you need multiple frontend origins, set `ALLOWED_ORIGINS` as a comma-separated list instead.
- `ENV=production` disables the verbose development exception handler in production.

Files added/changed
- `frontend/env.js` — runtime loader that sets `window.__API_BASE__` for local and production fallbacks.
- `frontend/favicon.svg` and `frontend/favicon.ico` — favicons to avoid 404s.
- `backend/app/routers/csv_validator.py` — robust CSV parsing, encoding sniffing, binary detection, and helpful 400 errors.
- `backend/app/main.py` — explicit CORS and development exception handler.
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
- Before the first Vercel deploy, verify the `API_BASE` env var points to the live Render service, not localhost.
