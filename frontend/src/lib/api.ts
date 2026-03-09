const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const payload = await res.clone().json() as { detail?: string; message?: string };
      detail = payload.detail || payload.message || '';
    } catch {
      detail = '';
    }
    throw new Error(
      detail ? `API error: ${res.status} ${detail}` : `API error: ${res.status} ${res.statusText}`
    );
  }
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
