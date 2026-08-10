import { supabase } from './supabaseClient';

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `API request failed (status ${status})`);
    this.status = status;
    this.detail = detail;
  }
}

// supabase.auth.getSession()이 세션 복원 중 네트워크 지연 등으로 응답 없이 멈추면
// 그 뒤의 fetch가 영영 시작되지 못해 화면이 "불러오는 중"에서 멈춘다(게스트가
// 위키처럼 여러 초기 조회를 순차로 거는 페이지에서 특히 눈에 띈다). 5초 안에 세션을
// 못 읽으면 토큰 없이(게스트로) 진행한다 — 로그인된 사용자라면 이어지는 요청이
// 401로 실패해 dashboardApi.js의 재시도가 잡아준다.
const SESSION_TIMEOUT_MS = 5000;

async function getAuthHeaders() {
  try {
    const { data } = await Promise.race([
      supabase.auth.getSession(),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('session lookup timed out')), SESSION_TIMEOUT_MS),
      ),
    ]);
    const token = data.session?.access_token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

// 백엔드가 응답 없이 멈추는 경우에도 화면이 무한 로딩에 빠지지 않도록 요청 자체에
// 상한을 둔다 — 타임아웃되면 일반 네트워크 에러처럼 처리돼 각 서비스의 폴백/에러
// 화면으로 이어진다.
const REQUEST_TIMEOUT_MS = 15000;

function withTimeout() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
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
  const { signal, clear } = withTimeout();

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
      },
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } finally {
    clear();
  }

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
  const { signal, clear } = withTimeout();

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: authHeaders,
      body: formData,
      signal,
    });
  } finally {
    clear();
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }
  return res.json();
}

export async function apiFetchBlob(path, { method = 'GET', body } = {}) {
  const authHeaders = await getAuthHeaders();
  const { signal, clear } = withTimeout();

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        ...authHeaders,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } finally {
    clear();
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }

  return {
    blob: await res.blob(),
    filename: getResponseFilename(res),
    contentType: res.headers.get('content-type') || '',
  };
}
