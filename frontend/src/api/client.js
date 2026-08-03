// FastAPI(src/api/main.py) 공용 fetch 래퍼.
// Supabase 세션의 access_token을 Authorization 헤더에 자동으로 실어 보낸다.
// 필요 env: VITE_API_BASE_URL (예: http://localhost:8000)
import { supabase } from './supabaseClient';

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `API 요청 실패 (status ${status})`);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch(path, { method = 'GET', body } = {}) {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new ApiError(res.status, payload?.detail);
  }
  if (res.status === 204) return null;
  return res.json();
}
