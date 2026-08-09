import { supabase } from './supabaseClient';

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `API request failed (status ${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function getAuthHeaders() {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseErrorDetail(res) {
  const payload = await res.json().catch(() => null);
  return payload?.detail;
}

function getResponseFilename(res) {
  const disposition = res.headers.get('content-disposition') || '';
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    return decodeURIComponent(encodedMatch[1].replace(/"/g, ''));
  }

  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] || null;
}

export async function apiFetch(path, { method = 'GET', body } = {}) {
  const authHeaders = await getAuthHeaders();

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }
  if (res.status === 204) return null;
  return res.json();
}

// multipart/form-data 업로드 전용 — apiFetch와 달리 Content-Type을 직접 지정하지
// 않는다(브라우저가 boundary를 포함한 값을 자동으로 채워야 하므로, 여기서 지정하면
// boundary가 빠져 서버가 파싱하지 못한다).
export async function apiFetchUpload(path, formData) {
  const authHeaders = await getAuthHeaders();

  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: authHeaders,
    body: formData,
  });

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }
  return res.json();
}

export async function apiFetchBlob(path, { method = 'GET', body } = {}) {
  const authHeaders = await getAuthHeaders();

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      ...authHeaders,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }

  return {
    blob: await res.blob(),
    filename: getResponseFilename(res),
    contentType: res.headers.get('content-type') || '',
  };
}
