import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiClient, ApiError, isPublicReadablePath } from './client';

describe('ApiClient', () => {
  let apiClient: ApiClient;

  beforeEach(() => {
    apiClient = new ApiClient('http://localhost:8000');
    global.fetch = vi.fn();
  });

  it('should make a GET request', async () => {
    const mockResponse = { id: '1', name: 'Test' };
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => mockResponse,
    });

    const result = await apiClient.get('/api/v1/test');

    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/test',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      })
    );
    expect(result).toEqual(mockResponse);
  });

  it('should make a POST request', async () => {
    const mockData = { name: 'Test' };
    const mockResponse = { id: '1', ...mockData };
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => mockResponse,
    });

    const result = await apiClient.post('/api/v1/test', mockData);

    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/test',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(mockData),
      })
    );
    expect(result).toEqual(mockResponse);
  });

  it('should throw an error on failed request', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Not found' }),
    });

    await expect(apiClient.get('/api/v1/test')).rejects.toThrow('Not found');
  });

  it('exposes the parsed JSON body via ApiError.body (Phase 15 Batch 5b R3 Minor 4)', async () => {
    // FastAPI 422 detail arrays must reach the caller untouched so
    // per-line CIDR validation messages can be rendered by
    // `extractInvalidLines` without a second fetch.
    const detailArray = [
      {
        loc: ['body', 'allowed_ip_cidrs', 0],
        msg: 'value is not a valid IPv4 or IPv6 network',
        type: 'value_error',
      },
    ];
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: detailArray }),
    });

    let captured: ApiError | null = null;
    try {
      await apiClient.post('/api/v1/test', { allowed_ip_cidrs: ['bad'] });
    } catch (err) {
      captured = err as ApiError;
    }
    expect(captured).not.toBeNull();
    expect(captured!).toBeInstanceOf(ApiError);
    expect(captured!.status).toBe(422);
    expect(captured!.body).toEqual({ detail: detailArray });
    // `detail` was an array, so the legacy detail string stays
    // unset (we only promote string detail to the message).
    expect(captured!.detail).toBeUndefined();
    expect(captured!.message).toBe('Request failed');
  });

  it('falls back to body=null when the error response is non-JSON (Phase 15 Batch 5b R3 Minor 4)', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json');
      },
    });

    let captured: ApiError | null = null;
    try {
      await apiClient.get('/api/v1/test');
    } catch (err) {
      captured = err as ApiError;
    }
    expect(captured).not.toBeNull();
    expect(captured!.status).toBe(502);
    expect(captured!.body).toBeNull();
    expect(captured!.message).toBe('Request failed');
  });
});

describe('isPublicReadablePath', () => {
  it('matches the project list and detail endpoints', () => {
    expect(isPublicReadablePath('/web-api/v1/projects')).toBe(true);
    expect(isPublicReadablePath('/web-api/v1/projects/')).toBe(true);
    expect(isPublicReadablePath('/web-api/v1/projects?page=1&limit=20')).toBe(true);
    expect(isPublicReadablePath('/web-api/v1/projects/abc-123')).toBe(true);
    expect(
      isPublicReadablePath('/web-api/v1/projects/abc-123/recordings?limit=50')
    ).toBe(true);
  });

  it('rejects nested non-public endpoints', () => {
    expect(isPublicReadablePath('/web-api/v1/projects/abc/members')).toBe(false);
    expect(isPublicReadablePath('/web-api/v1/projects/abc/trusted-users')).toBe(
      false
    );
    expect(
      isPublicReadablePath('/web-api/v1/projects/abc/recordings/r1/audio')
    ).toBe(false);
    expect(isPublicReadablePath('/api/v1/users/me')).toBe(false);
  });

  it('rejects mutating verbs even for matching paths', () => {
    expect(isPublicReadablePath('/web-api/v1/projects', 'POST')).toBe(false);
    expect(isPublicReadablePath('/web-api/v1/projects/abc', 'PATCH')).toBe(false);
    expect(isPublicReadablePath('/web-api/v1/projects/abc', 'DELETE')).toBe(
      false
    );
  });
});

describe('ApiClient public-path behaviour', () => {
  let apiClient: ApiClient;

  beforeEach(() => {
    apiClient = new ApiClient('http://localhost:8000');
    global.fetch = vi.fn();
  });

  it('attaches Authorization header for public-readable paths when signed in (Round 2)', async () => {
    // Round 2 致命: the original behaviour stripped Bearer on public paths
    // even when the user was signed in, which combined with
    // `credentials: 'include'` (session cookie) caused the backend session
    // branch to 401 because `access_token` was missing. The fix keeps
    // Bearer attached whenever an accessToken is present.
    apiClient.setAccessToken('valid-jwt');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ items: [], total: 0, page: 1 }),
    });

    await apiClient.get('/web-api/v1/projects?page=1');

    const calledWith = (global.fetch as ReturnType<typeof vi.fn>).mock
      .calls[0]![1] as RequestInit & { headers: Record<string, string> };
    expect(calledWith.headers.Authorization).toBe('Bearer valid-jwt');
    // Authenticated visitors keep cookies so their session can authenticate.
    expect(calledWith.credentials).toBe('include');
  });

  it('strips Authorization and cookies on public paths for guests (Round 2 case B)', async () => {
    // Guest = no access token in memory. The request must go fully
    // anonymous: no Authorization header AND `credentials: 'omit'` so a
    // stale `echoroo_session` cookie left over from a previous session
    // cannot force the backend into the session-required branch.
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ items: [], total: 0, page: 1 }),
    });

    await apiClient.get('/web-api/v1/projects?page=1');

    const calledWith = (global.fetch as ReturnType<typeof vi.fn>).mock
      .calls[0]![1] as RequestInit & { headers: Record<string, string> };
    expect(calledWith.headers.Authorization).toBeUndefined();
    expect(calledWith.credentials).toBe('omit');
  });

  it('falls back to anonymous Guest retry on 401 from a public path (Round 2 case C)', async () => {
    // Authenticated caller: first attempt sends Bearer + cookies and
    // gets 401 (e.g. session expired but Bearer + cookie were both
    // sent). The client must transparently retry once with
    // `credentials: 'omit'` and no Authorization so the Guest fast-path
    // admits the request.
    apiClient.setAccessToken('valid-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ detail: 'Unauthorized' }),
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ items: [], total: 0, page: 1 }),
    });

    await apiClient.get('/web-api/v1/projects?page=1');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstCall = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(firstCall.headers.Authorization).toBe('Bearer valid-jwt');
    expect(firstCall.credentials).toBe('include');

    const retryCall = fetchMock.mock.calls[1]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(retryCall.headers.Authorization).toBeUndefined();
    expect(retryCall.credentials).toBe('omit');
  });

  it('still attaches Authorization on private paths', async () => {
    apiClient.setAccessToken('valid-jwt');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ id: 'me' }),
    });

    await apiClient.get('/api/v1/users/me');

    const calledWith = (global.fetch as ReturnType<typeof vi.fn>).mock
      .calls[0]![1] as RequestInit & { headers: Record<string, string> };
    expect(calledWith.headers.Authorization).toBe('Bearer valid-jwt');
  });

  it('does not attempt token refresh on a 401 from a public path', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ detail: 'Unauthorized' }),
    });

    await expect(
      apiClient.get('/web-api/v1/projects/abc-123')
    ).rejects.toThrow('Unauthorized');

    // Only ONE fetch call — no auth refresh retry.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe(
      'http://localhost:8000/web-api/v1/projects/abc-123'
    );
  });

  it('latches refresh after 401 to break refresh loops', async () => {
    apiClient.setAccessToken('expired-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;

    // First call: protected endpoint returns 401.
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ detail: 'Unauthorized' }),
    });
    // Refresh attempt itself returns 401 — the latch must engage.
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ detail: 'Refresh expired' }),
    });

    await expect(apiClient.get('/api/v1/users/me')).rejects.toThrow();
    const callsAfterFirst = fetchMock.mock.calls.length;
    expect(callsAfterFirst).toBe(2); // original + refresh

    // Second protected call: latch should prevent any new refresh attempt.
    // The retry path now skips refresh entirely and just surfaces the 401.
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: { get: (_key: string) => 'application/json' },
      json: async () => ({ detail: 'Unauthorized' }),
    });

    await expect(apiClient.get('/api/v1/users/me')).rejects.toThrow();
    // Only ONE additional fetch (the protected request itself) — refresh
    // was suppressed by the latch.
    expect(fetchMock.mock.calls.length).toBe(callsAfterFirst + 1);
  });
});
