// DataForge — Shared Config & API Helper

// Runtime API base (supports an injected `window.__API_BASE__` set by /env.js)
const isLocal = /^(localhost|127\.0\.0\.1|::1?|\[.*\])$/.test(window.location.hostname);
const configuredApiBase = typeof window.__API_BASE__ === 'string' ? window.__API_BASE__.trim() : '';

if (!configuredApiBase && !isLocal) {
  console.warn('DataForge API base is not configured. Add API_BASE during the frontend build so deployed pages can reach Render.');
}

const API_BASE = configuredApiBase || (isLocal ? 'http://localhost:8000' : '');

async function apiGet(path) {
  if (!API_BASE) throw new Error('API base URL is not configured.');
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiPost(path, body) {
  if (!API_BASE) throw new Error('API base URL is not configured.');
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok && res.status !== 422) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return { data, status: res.status };
}

async function apiUpload(path, file, extraParams = {}) {
  if (!API_BASE) throw new Error('API base URL is not configured.');
  const form = new FormData();
  form.append('file', file);
  for (const [k, v] of Object.entries(extraParams)) {
    form.append(k, v);
  }
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: form });
  const data = await res.json();
  if (!res.ok && res.status !== 422) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return { data, status: res.status };
}

// ── UI Helpers ────────────────────────────────────────
function showLoading(id = 'loading') {
  const el = document.getElementById(id);
  if (el) el.classList.add('active');
}

function hideLoading(id = 'loading') {
  const el = document.getElementById(id);
  if (el) el.classList.remove('active');
}

function showResults(id = 'results') {
  const el = document.getElementById(id);
  if (el) el.classList.add('active');
}

function hideResults(id = 'results') {
  const el = document.getElementById(id);
  if (el) el.classList.remove('active');
}

function setupFileUpload(zoneId, inputId, nameId) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const nameEl = document.getElementById(nameId);

  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      if (nameEl) { nameEl.textContent = e.dataTransfer.files[0].name; nameEl.style.display = 'block'; }
    }
  });
  input.addEventListener('change', () => {
    if (input.files.length && nameEl) {
      nameEl.textContent = input.files[0].name;
      nameEl.style.display = 'block';
    }
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

async function loadDemoFile(url, filename, mimeType = 'text/csv') {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not load demo file: ${filename}`);
  const blob = await res.blob();
  return new File([blob], filename, { type: blob.type || mimeType });
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadText(filename, text, mimeType = 'text/plain;charset=utf-8') {
  downloadBlob(filename, new Blob([text], { type: mimeType }));
}

function downloadJson(filename, data) {
  downloadText(filename, JSON.stringify(data, null, 2), 'application/json;charset=utf-8');
}
