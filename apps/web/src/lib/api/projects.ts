/**
 * Projects API endpoints
 */

import type {
  Project,
  ProjectMember,
  ProjectListResponse,
  ProjectCreateRequest,
  ProjectUpdateRequest,
  ProjectMemberAddRequest,
  ProjectMemberUpdateRequest,
} from '$lib/types';
import { apiClient } from './client';

export const projectsApi = {
  /**
   * List all projects accessible to the current user
   */
  list: async (params?: { page?: number; limit?: number }): Promise<ProjectListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.limit) queryParams.set('limit', params.limit.toString());

    const query = queryParams.toString();
    const endpoint = `/api/v1/projects${query ? `?${query}` : ''}`;

    return apiClient.get<ProjectListResponse>(endpoint);
  },

  /**
   * Get a single project by ID
   */
  get: async (projectId: string): Promise<Project> => {
    return apiClient.get<Project>(`/api/v1/projects/${projectId}`);
  },

  /**
   * Create a new project
   */
  create: async (data: ProjectCreateRequest): Promise<Project> => {
    return apiClient.post<Project>('/api/v1/projects', data);
  },

  /**
   * Update a project (admin only)
   */
  update: async (projectId: string, data: ProjectUpdateRequest): Promise<Project> => {
    return apiClient.patch<Project>(`/api/v1/projects/${projectId}`, data);
  },

  /**
   * Delete a project (owner only)
   */
  delete: async (projectId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/projects/${projectId}`);
  },

  /**
   * List project members
   */
  listMembers: async (projectId: string): Promise<ProjectMember[]> => {
    return apiClient.get<ProjectMember[]>(`/api/v1/projects/${projectId}/members`);
  },

  /**
   * Add a member to the project (admin only)
   */
  addMember: async (projectId: string, data: ProjectMemberAddRequest): Promise<ProjectMember> => {
    return apiClient.post<ProjectMember>(`/api/v1/projects/${projectId}/members`, data);
  },

  /**
   * Update member role (admin only)
   */
  updateMemberRole: async (
    projectId: string,
    userId: string,
    data: ProjectMemberUpdateRequest
  ): Promise<ProjectMember> => {
    return apiClient.patch<ProjectMember>(
      `/api/v1/projects/${projectId}/members/${userId}`,
      data
    );
  },

  /**
   * Remove a member from the project (admin only)
   */
  removeMember: async (projectId: string, userId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/projects/${projectId}/members/${userId}`);
  },
};
