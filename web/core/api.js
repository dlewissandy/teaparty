// HTTP client with retry, auth, and timeout.
// Port of modules/api.js, adapted for the reactive store.

let _store = null;
let _onUnauthorized = null;

export function initApi(store, onUnauthorized) {
  _store = store;
  _onUnauthorized = onUnauthorized;
}

export async function api(path, options = {}) {
  const maxRetries = options.retries ?? 2;
  const timeoutMs = options.timeout ?? 30000;
  const retryDelays = [200, 600, 1500];

  const headers = { ...(options.headers || {}) };
  const token = _store?.get().auth.token;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }

  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (attempt > 0) {
      await new Promise(r => setTimeout(r, retryDelays[attempt - 1] || 1500));
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(path, { ...options, headers, body, signal: controller.signal });
      clearTimeout(timer);

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const error = new Error(payload.detail || `Request failed: ${response.status}`);
        error.status = response.status;

        if (response.status === 401 && token) {
          if (_onUnauthorized) _onUnauthorized();
        }

        // Don't retry client errors (4xx)
        if (response.status >= 400 && response.status < 500) {
          throw error;
        }

        lastError = error;
        continue;
      }

      if (response.status === 204) return null;
      return response.json();
    } catch (err) {
      clearTimeout(timer);
      if (err.name === 'AbortError') {
        lastError = new Error('Request timed out');
        lastError.status = 0;
      } else if (err.status >= 400 && err.status < 500) {
        throw err;
      } else {
        lastError = err;
      }
    }
  }

  throw lastError;
}
