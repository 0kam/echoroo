import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiClient } from './client';

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
});
