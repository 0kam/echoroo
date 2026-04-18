/**
 * Setup API client
 * Handles initial setup and wizard-related operations
 */

import { apiClient } from './client';
import type {
  User,
  SetupInitializeRequest,
} from '$lib/types';

// Re-export types for convenience
export type { SetupInitializeRequest };

/**
 * Initialize system setup by creating first admin user
 * @param data - Admin user credentials and info
 * @returns Created admin user
 */
export async function initializeSetup(data: SetupInitializeRequest): Promise<User> {
  return apiClient.post<User>('/api/v1/setup/initialize', data);
}
