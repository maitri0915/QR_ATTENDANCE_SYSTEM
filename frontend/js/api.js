/**
 * Shared API client + auth/session helpers for the QR Attendance System frontend.
 * Loaded on every page before the page-specific script.
 */
const API_BASE = ""; // same-origin — FastAPI serves both the API and these static files

const Auth = {
  saveSession(data) {
    localStorage.setItem("qr_token", data.access_token);
    localStorage.setItem("qr_role", data.role);
    localStorage.setItem("qr_profile_id", data.profile_id);
    localStorage.setItem("qr_full_name", data.full_name || "");
  },
  token() { return localStorage.getItem("qr_token"); },
  role() { return localStorage.getItem("qr_role"); },
  profileId() { return localStorage.getItem("qr_profile_id"); },
  fullName() { return localStorage.getItem("qr_full_name"); },
  logout() {
    localStorage.clear();
    window.location.href = "/login.html";
  },
  /** Redirect to login if not authenticated, or if role doesn't match this page. */
  guard(requiredRole) {
    if (!this.token() || this.role() !== requiredRole) {
      window.location.href = "/login.html";
    }
  },
};

const Api = {
  async request(path, { method = "GET", body = null, auth = true, isForm = false } = {}) {
    const headers = {};
    if (!isForm) headers["Content-Type"] = "application/json";
    if (auth && Auth.token()) headers["Authorization"] = `Bearer ${Auth.token()}`;

    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    });

    if (res.status === 401) {
      Auth.logout();
      return;
    }

    const contentType = res.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await res.json() : await res.text();

    if (!res.ok) {
      const message = (payload && payload.detail) ? payload.detail : "Something went wrong. Please try again.";
      throw new Error(message);
    }
    return payload;
  },

  get(path) { return this.request(path); },
  post(path, body) { return this.request(path, { method: "POST", body }); },
  put(path, body) { return this.request(path, { method: "PUT", body }); },
  del(path) { return this.request(path, { method: "DELETE" }); },
};

/** Small helper to render a fetch error into an on-page element. */
function showError(el, err) {
  if (!el) return;
  el.textContent = err.message || String(err);
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 5000);
}

function showSuccess(el, message) {
  if (!el) return;
  el.textContent = message;
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 4000);
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function statusPill(status) {
  const label = status === "not_marked" ? "Not marked" : status;
  return `<span class="status-pill status-${status}">${label}</span>`;
}
