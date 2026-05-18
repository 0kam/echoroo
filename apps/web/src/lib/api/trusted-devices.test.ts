import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient, ApiError } from './client';
import {
  listTrustedDevices,
  revokeAllTrustedDevices,
  revokeTrustedDevice,
} from './trusted-devices';

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (_key: string) => 'application/json' },
    json: async () => body,
  };
}

function emptyResponse(status = 204) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (_key: string) => null },
    json: async () => ({}),
  };
}

describe('trusted-devices API client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiClient.setAccessToken(null);
    global.fetch = vi.fn();
    document.cookie = 'echoroo_session=; Max-Age=0; path=/';
    document.cookie = 'echoroo_csrf=; Max-Age=0; path=/';
    document.cookie = 'echoroo_session=session-cookie; path=/';
  });

  it('lists trusted devices through the account BFF with cookie credentials and no CSRF header', async () => {
    apiClient.setAccessToken('valid-jwt');
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        devices: [
          {
            id: '6e07e641-8cd0-47d7-a808-9407a82297d7',
            label: 'Work laptop',
            created_at: '2026-05-18T01:00:00Z',
            last_used_at: '2026-05-18T02:00:00Z',
            expires_at: '2026-06-17T01:00:00Z',
            current_device: true,
            last_seen_hint: 'Chrome on Linux',
          },
        ],
      })
    );

    const result = await listTrustedDevices();

    expect(result.devices).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/account/trusted-devices',
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
      })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBe('Bearer valid-jwt');
    expect(call.headers['X-CSRF-Token']).toBeUndefined();
  });

  it('omits Authorization on list requests when no access token is available', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ devices: [] }));

    await listTrustedDevices();

    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.credentials).toBe('include');
    expect(call.headers.Authorization).toBeUndefined();
    expect(call.headers['X-CSRF-Token']).toBeUndefined();
  });

  it('revokes one trusted device through the account BFF with a CSRF header', async () => {
    apiClient.setAccessToken('valid-jwt');
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(emptyResponse());

    await revokeTrustedDevice('6e07e641-8cd0-47d7-a808-9407a82297d7');

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/account/trusted-devices/6e07e641-8cd0-47d7-a808-9407a82297d7',
      expect.objectContaining({
        method: 'DELETE',
        credentials: 'include',
      })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBe('Bearer valid-jwt');
    expect(call.headers['X-CSRF-Token']).toBe('test-csrf');
  });

  it('revokes all trusted devices through the account BFF with a CSRF header', async () => {
    apiClient.setAccessToken('valid-jwt');
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(emptyResponse());

    await revokeAllTrustedDevices();

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/account/trusted-devices/revoke-all',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBe('Bearer valid-jwt');
    expect(call.headers['X-CSRF-Token']).toBe('test-csrf');
  });

  it('preserves account error envelopes on ApiError.code', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error_code: 'trusted_device_not_found',
          message: 'Trusted device is not available.',
        },
        404
      )
    );

    let captured: ApiError | null = null;
    try {
      await revokeTrustedDevice('6e07e641-8cd0-47d7-a808-9407a82297d7');
    } catch (err) {
      captured = err as ApiError;
    }

    expect(captured).toBeInstanceOf(ApiError);
    expect(captured!.status).toBe(404);
    expect(captured!.message).toBe('Trusted device is not available.');
    expect(captured!.code).toBe('trusted_device_not_found');
  });
});
