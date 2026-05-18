import { ApiError, apiClient } from './client';

const BASE = '/web-api/v1/account/trusted-devices';
const CSRF_COOKIE_NAME = 'echoroo_csrf';

export interface TrustedDevice {
  id: string;
  label: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
  current_device: boolean;
  last_seen_hint?: string | null;
}

export interface TrustedDevicesResponse {
  devices: TrustedDevice[];
}

function resolveBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return '';
  }
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
}

function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${CSRF_COOKIE_NAME}=`;
  const parts = document.cookie ? document.cookie.split('; ') : [];
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      try {
        return decodeURIComponent(part.slice(prefix.length));
      } catch {
        return part.slice(prefix.length);
      }
    }
  }
  return null;
}

function getStringField(
  obj: Record<string, unknown>,
  fields: readonly string[]
): string | null {
  for (const field of fields) {
    const value = obj[field];
    if (typeof value === 'string' && value.length > 0) {
      return value;
    }
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function extractErrorCode(errorData: unknown): string | null {
  const obj = asRecord(errorData);
  if (!obj) return null;

  const topLevel = getStringField(obj, ['error', 'code', 'error_code']);
  if (topLevel) return topLevel;

  const detail = asRecord(obj.detail);
  return detail ? getStringField(detail, ['error', 'code', 'error_code']) : null;
}

function extractErrorMessage(errorData: unknown): string {
  const obj = asRecord(errorData);
  if (!obj) return 'Request failed';

  const detail = obj.detail;
  if (typeof detail === 'string' && detail.length > 0) return detail;

  const detailObj = asRecord(detail);
  if (detailObj) {
    const nestedMessage = getStringField(detailObj, ['message', 'detail']);
    if (nestedMessage) return nestedMessage;
  }

  return getStringField(obj, ['message', 'detail']) ?? 'Request failed';
}

async function request<T>(path: string, method: 'GET' | 'POST' | 'DELETE'): Promise<T> {
  const headers: Record<string, string> = {};
  const accessToken = apiClient.getAccessToken();
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  if (method !== 'GET') {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
    }
  }

  const response = await fetch(`${resolveBaseUrl()}${BASE}${path}`, {
    method,
    credentials: 'include',
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const message = extractErrorMessage(errorData);
    throw new ApiError(
      message,
      response.status,
      message,
      extractErrorCode(errorData),
      errorData
    );
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType?.includes('application/json')) {
    return (await response.json()) as T;
  }
  return {} as T;
}

export function listTrustedDevices(): Promise<TrustedDevicesResponse> {
  return request<TrustedDevicesResponse>('', 'GET');
}

export function revokeTrustedDevice(deviceId: string): Promise<void> {
  return request<void>(`/${encodeURIComponent(deviceId)}`, 'DELETE');
}

export function revokeAllTrustedDevices(): Promise<void> {
  return request<void>('/revoke-all', 'POST');
}
