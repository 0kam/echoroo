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
    vi.restoreAllMocks();
    apiClient.setAccessToken(null);
    global.fetch = vi.fn();
    document.cookie = 'echoroo_session=; Max-Age=0; path=/';
    document.cookie = 'echoroo_csrf=; Max-Age=0; path=/';
    document.cookie = 'echoroo_session=stale-session; path=/';
  });

  it('reads project lists as an anonymous Guest when no access token is usable', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, page: 1 }));

    await projectsApi.list({ page: 1, limit: 20 });

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/projects/?page=1&limit=20',
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

  it('keeps trusted-users BFF reads on cookie credentials with Authorization', async () => {
    apiClient.setAccessToken('valid-jwt');
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
    expect(call.headers.Authorization).toBe('Bearer valid-jwt');
  });

  it('refreshes a missing access token before private BFF requests', async () => {
    const refreshSpy = vi.spyOn(apiClient, 'refreshToken').mockImplementation(async () => {
      apiClient.setAccessToken('refreshed-jwt');
    });
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 'project-1', name: 'Project' }));

    await projectsApi.create({
      name: 'Project',
      visibility: 'public',
      license_id: 'cc-by',
    });

    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/projects/',
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBe('Bearer refreshed-jwt');
    expect(call.headers['X-CSRF-Token']).toBe('test-csrf');
  });

  it('lets the BFF surface auth errors when refresh cannot restore a token', async () => {
    const refreshSpy = vi
      .spyOn(apiClient, 'refreshToken')
      .mockRejectedValue(new ApiError('Token refresh failed', 401));
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error_code: 'auth_required',
          message: 'Session cookie + access token required',
        },
        401
      )
    );

    await expect(
      projectsApi.create({
        name: 'Project',
        visibility: 'public',
        license_id: 'cc-by',
      })
    ).rejects.toMatchObject({
      status: 401,
      message: 'Session cookie + access token required',
    });

    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe('/web-api/v1/projects/');
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes('/api/v1/'))
    ).toBe(false);
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBeUndefined();
  });

  it('routes project members and overview through the BFF cookie surface', async () => {
    apiClient.setAccessToken('valid-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        sites: [],
        recording_calendar: [],
        total_recordings: 0,
        total_sites: 0,
        total_duration: 0,
      })
    );

    await projectsApi.listMembers('project-1');
    await projectsApi.getOverview('project-1');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/web-api/v1/projects/project-1/members',
      expect.objectContaining({ method: 'GET', credentials: 'include' })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/web-api/v1/projects/project-1/overview',
      expect.objectContaining({ method: 'GET', credentials: 'include' })
    );
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit & { headers: Record<string, string> };
      expect(init.headers.Authorization).toBe('Bearer valid-jwt');
    }
  });

  it('routes project mutations through BFF with CSRF', async () => {
    apiClient.setAccessToken('valid-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    fetchMock.mockResolvedValue(jsonResponse({ id: 'project-1', name: 'Project' }));

    await projectsApi.create({
      name: 'Project',
      visibility: 'public',
      license_id: 'cc-by',
    });
    await projectsApi.update('project-1', { name: 'Renamed' });
    await projectsApi.delete('project-1');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/web-api/v1/projects/',
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/web-api/v1/projects/project-1',
      expect.objectContaining({ method: 'PATCH', credentials: 'include' })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/web-api/v1/projects/project-1',
      expect.objectContaining({ method: 'DELETE', credentials: 'include' })
    );
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit & { headers: Record<string, string> };
      expect(init.headers.Authorization).toBe('Bearer valid-jwt');
      expect(init.headers['X-CSRF-Token']).toBe('test-csrf');
    }
  });

  it('routes member mutations through BFF with CSRF', async () => {
    // SU-bootstrap redesign (preview feedback #7): direct member-add was
    // removed (POST /projects/{id}/members no longer exists). Only the
    // role-change + remove mutations remain on the members page.
    apiClient.setAccessToken('valid-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    fetchMock.mockResolvedValue(jsonResponse({ id: 'member-1', role: 'member' }));

    await projectsApi.updateMemberRole('project-1', 'user-1', { role: 'member' });
    await projectsApi.removeMember('project-1', 'user-1');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/web-api/v1/projects/project-1/members/user-1',
      expect.objectContaining({ method: 'PATCH', credentials: 'include' })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/web-api/v1/projects/project-1/members/user-1',
      expect.objectContaining({ method: 'DELETE', credentials: 'include' })
    );
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit & { headers: Record<string, string> };
      expect(init.headers.Authorization).toBe('Bearer valid-jwt');
      expect(init.headers['X-CSRF-Token']).toBe('test-csrf');
    }
  });

  it('routes transfer-ownership through BFF with CSRF and idempotency key', async () => {
    apiClient.setAccessToken('valid-jwt');
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    document.cookie = 'echoroo_csrf=test-csrf; path=/';
    fetchMock.mockResolvedValue(
      jsonResponse({
        project_id: 'project-1',
        previous_owner_id: 'owner-1',
        new_owner_id: 'user-1',
        replayed: false,
      })
    );

    await projectsApi.transferOwnership('project-1', 'user-1', 'idem-key-123');

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/projects/project-1/transfer-ownership',
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    );
    const firstCall = fetchMock.mock.calls[0];
    expect(firstCall).toBeDefined();
    const init = firstCall![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(init.headers.Authorization).toBe('Bearer valid-jwt');
    expect(init.headers['X-CSRF-Token']).toBe('test-csrf');
    expect(init.headers['X-Idempotency-Key']).toBe('idem-key-123');
    expect(init.body).toBe(JSON.stringify({ new_owner_user_id: 'user-1' }));
  });
});
