import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient, ApiError } from './client';
import { projectsApi } from './projects';

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (_key: string) => 'application/json' },
    json: async () => body,
  };
}

describe('projectsApi BFF public-read behaviour', () => {
  beforeEach(() => {
    apiClient.setAccessToken(null);
    global.fetch = vi.fn();
    document.cookie = 'echoroo_session=stale-session; path=/';
  });

  it('reads project lists as an anonymous Guest when no access token is usable', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, page: 1 }));

    await projectsApi.list({ page: 1, limit: 20 });

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/projects?page=1&limit=20',
      expect.objectContaining({
        method: 'GET',
        credentials: 'omit',
      })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBeUndefined();
  });

  it('preserves public-detail 404s instead of forcing stale-cookie 401s', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'project not found' }, 404));

    let captured: ApiError | null = null;
    try {
      await projectsApi.get('missing-project');
    } catch (err) {
      captured = err as ApiError;
    }

    expect(captured).toBeInstanceOf(ApiError);
    expect(captured!.status).toBe(404);
    const call = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(call.credentials).toBe('omit');
  });

  it('retries authenticated public reads once as Guest after a 401', async () => {
    apiClient.setAccessToken('stale-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Unauthorized' }, 401));
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 'public-project', visibility: 'public' }));

    await projectsApi.get('public-project');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstCall = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(firstCall.credentials).toBe('include');
    expect(firstCall.headers.Authorization).toBe('Bearer stale-jwt');

    const retryCall = fetchMock.mock.calls[1]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(retryCall.credentials).toBe('omit');
    expect(retryCall.headers.Authorization).toBeUndefined();
  });

  it('keeps trusted-users BFF reads on cookie credentials without Authorization', async () => {
    apiClient.setAccessToken('stale-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await projectsApi.listTrustedUsers('project-1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/projects/project-1/trusted-users',
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
      })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBeUndefined();
  });
});
