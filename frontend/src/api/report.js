import { apiFetch, apiFetchBlob } from './client';

export function fetchDailyReport(date) {
  const q = date ? `?date=${encodeURIComponent(date)}` : '';
  return apiFetch(`/reports/daily${q}`);
}

export function fetchDailyReportHistory(limit = 30) {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiFetch(`/reports/daily/history?${params.toString()}`);
}

export function downloadDailyReport(date, format) {
  const params = new URLSearchParams({ date, format });
  return apiFetchBlob(`/reports/daily/download?${params.toString()}`);
}

export function generateDailyReport(date, options = {}) {
  return apiFetch('/reports/daily/generate', {
    method: 'POST',
    body: {
      date,
      ...options,
    },
  });
}
