import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from './client';
import { searchGBIF, searchTaxa } from './taxa';

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (_key: string) => 'application/json' },
    json: async () => body,
  };
}

describe('taxa API BFF behaviour', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiClient.setAccessToken('valid-jwt');
    global.fetch = vi.fn();
  });

  it('routes local taxa search through the BFF surface', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await searchTaxa('アオ', 'ja', 5);

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/taxa/search?q=%E3%82%A2%E3%82%AA&locale=ja&limit=5',
      expect.objectContaining({ method: 'GET', credentials: 'include' })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBe('Bearer valid-jwt');
  });

  it('routes GBIF taxa search through the BFF surface', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await searchGBIF('Parus major', 3);

    expect(fetchMock).toHaveBeenCalledWith(
      '/web-api/v1/taxa/gbif-search?q=Parus+major&limit=3',
      expect.objectContaining({ method: 'GET', credentials: 'include' })
    );
    const call = fetchMock.mock.calls[0]![1] as RequestInit & {
      headers: Record<string, string>;
    };
    expect(call.headers.Authorization).toBe('Bearer valid-jwt');
  });
});
