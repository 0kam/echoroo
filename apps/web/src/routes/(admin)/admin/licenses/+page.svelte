<script lang="ts">
  /**
   * Admin - License Management Page
   */

  import { licenseApi } from '$lib/api/licenses';
  import { ApiError } from '$lib/api/client';
  import type { License, LicenseCreateRequest, LicenseUpdateRequest } from '$lib/types';

  // State
  let licenses = $state<License[]>([]);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);
  let showCreateModal = $state(false);
  let showEditModal = $state(false);
  let showDeleteModal = $state(false);
  let currentLicense = $state<License | null>(null);

  // Form state
  let formData = $state({
    id: '',
    name: '',
    short_name: '',
    url: '',
    description: '',
  });

  /**
   * Load licenses
   */
  async function loadLicenses() {
    isLoading = true;
    error = null;

    try {
      const response = await licenseApi.list();
      licenses = response.items;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to load licenses';
      }
    } finally {
      isLoading = false;
    }
  }

  // Load licenses on mount
  $effect(() => {
    loadLicenses();
  });

  /**
   * Open create modal
   */
  function openCreateModal() {
    formData = {
      id: '',
      name: '',
      short_name: '',
      url: '',
      description: '',
    };
    showCreateModal = true;
  }

  /**
   * Open edit modal
   */
  function openEditModal(license: License) {
    currentLicense = license;
    formData = {
      id: license.id,
      name: license.name,
      short_name: license.short_name,
      url: license.url || '',
      description: license.description || '',
    };
    showEditModal = true;
  }

  /**
   * Open delete modal
   */
  function openDeleteModal(license: License) {
    currentLicense = license;
    showDeleteModal = true;
  }

  /**
   * Close all modals
   */
  function closeModals() {
    showCreateModal = false;
    showEditModal = false;
    showDeleteModal = false;
    currentLicense = null;
  }

  /**
   * Handle create license
   */
  async function handleCreate() {
    error = null;

    try {
      const data: LicenseCreateRequest = {
        id: formData.id.trim(),
        name: formData.name.trim(),
        short_name: formData.short_name.trim(),
        url: formData.url.trim() || undefined,
        description: formData.description.trim() || undefined,
      };

      await licenseApi.create(data);
      successMessage = 'License created successfully';
      closeModals();
      await loadLicenses();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to create license';
      }
    }
  }

  /**
   * Handle update license
   */
  async function handleUpdate() {
    if (!currentLicense) return;

    error = null;

    try {
      const data: LicenseUpdateRequest = {
        name: formData.name.trim(),
        short_name: formData.short_name.trim(),
        url: formData.url.trim() || undefined,
        description: formData.description.trim() || undefined,
      };

      await licenseApi.update(currentLicense.id, data);
      successMessage = 'License updated successfully';
      closeModals();
      await loadLicenses();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to update license';
      }
    }
  }

  /**
   * Handle delete license
   */
  async function handleDelete() {
    if (!currentLicense) return;

    error = null;

    try {
      await licenseApi.delete(currentLicense.id);
      successMessage = 'License deleted successfully';
      closeModals();
      await loadLicenses();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to delete license';
      }
    }
  }

  /**
   * Format date
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString();
  }

  /**
   * Truncate text
   */
  function truncate(text: string | undefined, maxLength: number): string {
    if (!text) return '-';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  }
</script>

<svelte:head>
  <title>License Management - Admin - Echoroo</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-gray-900">License Management</h1>
      <p class="mt-2 text-sm text-gray-600">Manage licenses for recordings and datasets</p>
    </div>
    <button
      onclick={openCreateModal}
      class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
    >
      Add New License
    </button>
  </div>

  <!-- Success Message -->
  {#if successMessage}
    <div class="mb-6 rounded-md bg-green-50 p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-green-400"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-green-800">{successMessage}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-red-50 p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-red-400"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-red-800">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Licenses Table -->
  {#if isLoading}
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-blue-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>
  {:else if licenses.length === 0}
    <div class="rounded-lg border-2 border-dashed border-gray-300 p-12 text-center">
      <svg
        class="mx-auto h-12 w-12 text-gray-400"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
      <h3 class="mt-2 text-sm font-medium text-gray-900">No licenses found</h3>
      <p class="mt-1 text-sm text-gray-500">Get started by creating a new license.</p>
      <div class="mt-6">
        <button
          onclick={openCreateModal}
          class="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Add New License
        </button>
      </div>
    </div>
  {:else}
    <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                ID
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Name
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Short Name
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                URL
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Description
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Created
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 bg-white">
            {#each licenses as license (license.id)}
              <tr class="hover:bg-gray-50">
                <!-- ID -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="text-sm font-medium text-gray-900">{license.id}</div>
                </td>

                <!-- Name -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="text-sm text-gray-900">{license.name}</div>
                </td>

                <!-- Short Name -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="text-sm text-gray-900">{license.short_name}</div>
                </td>

                <!-- URL -->
                <td class="px-6 py-4">
                  {#if license.url}
                    <a
                      href={license.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      class="text-sm text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {truncate(license.url, 40)}
                    </a>
                  {:else}
                    <span class="text-sm text-gray-500">-</span>
                  {/if}
                </td>

                <!-- Description -->
                <td class="px-6 py-4">
                  <div class="max-w-xs text-sm text-gray-900">
                    {truncate(license.description, 60)}
                  </div>
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {formatDate(license.created_at)}
                </td>

                <!-- Actions -->
                <td class="whitespace-nowrap px-6 py-4 text-sm">
                  <div class="flex gap-2">
                    <button
                      onclick={() => openEditModal(license)}
                      class="rounded bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-200"
                    >
                      Edit
                    </button>
                    <button
                      onclick={() => openDeleteModal(license)}
                      class="rounded bg-red-100 px-3 py-1 text-xs font-medium text-red-700 transition-colors hover:bg-red-200"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>

<!-- Create Modal -->
{#if showCreateModal}
  <div class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-center justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={closeModals}
      ></div>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <h3 class="text-lg font-medium leading-6 text-gray-900" id="modal-title">
            Create New License
          </h3>
          <div class="mt-4 space-y-4">
            <!-- ID -->
            <div>
              <label for="create-id" class="block text-sm font-medium text-gray-700">
                ID <span class="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="create-id"
                bind:value={formData.id}
                required
                placeholder="e.g., CC-BY-4.0"
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- Name -->
            <div>
              <label for="create-name" class="block text-sm font-medium text-gray-700">
                Name <span class="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="create-name"
                bind:value={formData.name}
                required
                placeholder="e.g., Creative Commons Attribution 4.0 International"
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- Short Name -->
            <div>
              <label for="create-short-name" class="block text-sm font-medium text-gray-700">
                Short Name <span class="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="create-short-name"
                bind:value={formData.short_name}
                required
                placeholder="e.g., CC BY 4.0"
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- URL -->
            <div>
              <label for="create-url" class="block text-sm font-medium text-gray-700">
                URL
              </label>
              <input
                type="url"
                id="create-url"
                bind:value={formData.url}
                placeholder="https://creativecommons.org/licenses/by/4.0/"
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- Description -->
            <div>
              <label for="create-description" class="block text-sm font-medium text-gray-700">
                Description
              </label>
              <textarea
                id="create-description"
                bind:value={formData.description}
                rows="3"
                placeholder="License description..."
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              ></textarea>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleCreate}
            class="inline-flex w-full justify-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:w-auto"
          >
            Create
          </button>
          <button
            type="button"
            onclick={closeModals}
            class="mt-3 inline-flex w-full justify-center rounded-md bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:mt-0 sm:w-auto"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Edit Modal -->
{#if showEditModal && currentLicense}
  <div class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-center justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={closeModals}
      ></div>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <h3 class="text-lg font-medium leading-6 text-gray-900" id="modal-title">
            Edit License: {currentLicense.id}
          </h3>
          <div class="mt-4 space-y-4">
            <!-- Name -->
            <div>
              <label for="edit-name" class="block text-sm font-medium text-gray-700">
                Name <span class="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="edit-name"
                bind:value={formData.name}
                required
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- Short Name -->
            <div>
              <label for="edit-short-name" class="block text-sm font-medium text-gray-700">
                Short Name <span class="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="edit-short-name"
                bind:value={formData.short_name}
                required
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- URL -->
            <div>
              <label for="edit-url" class="block text-sm font-medium text-gray-700">
                URL
              </label>
              <input
                type="url"
                id="edit-url"
                bind:value={formData.url}
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <!-- Description -->
            <div>
              <label for="edit-description" class="block text-sm font-medium text-gray-700">
                Description
              </label>
              <textarea
                id="edit-description"
                bind:value={formData.description}
                rows="3"
                class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              ></textarea>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleUpdate}
            class="inline-flex w-full justify-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:w-auto"
          >
            Update
          </button>
          <button
            type="button"
            onclick={closeModals}
            class="mt-3 inline-flex w-full justify-center rounded-md bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:mt-0 sm:w-auto"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Delete Modal -->
{#if showDeleteModal && currentLicense}
  <div class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-center justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={closeModals}
      ></div>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-100 sm:mx-0 sm:h-10 sm:w-10">
              <svg class="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            </div>
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-lg font-medium leading-6 text-gray-900" id="modal-title">
                Delete License
              </h3>
              <div class="mt-2">
                <p class="text-sm text-gray-500">
                  Are you sure you want to delete the license "<strong>{currentLicense.name}</strong>" ({currentLicense.id})?
                  This action cannot be undone.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleDelete}
            class="inline-flex w-full justify-center rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 sm:ml-3 sm:w-auto"
          >
            Delete
          </button>
          <button
            type="button"
            onclick={closeModals}
            class="mt-3 inline-flex w-full justify-center rounded-md bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:mt-0 sm:w-auto"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
