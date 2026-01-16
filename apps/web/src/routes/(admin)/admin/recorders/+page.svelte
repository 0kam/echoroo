<script lang="ts">
  /**
   * Admin - Recorder Management Page
   */

  import { recorderApi } from '$lib/api/recorders';
  import { ApiError } from '$lib/api/client';
  import type { Recorder, RecorderCreateRequest, RecorderUpdateRequest } from '$lib/types';

  // State
  let recorders = $state<Recorder[]>([]);
  let total = $state(0);
  let page = $state(1);
  let limit = $state(20);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Modal state
  let showModal = $state(false);
  let modalMode = $state<'create' | 'edit'>('create');
  let editingRecorder = $state<Recorder | null>(null);

  // Form state
  let formData = $state({
    id: '',
    manufacturer: '',
    recorder_name: '',
    version: '',
  });

  // Delete confirmation
  let deleteConfirmRecorder = $state<Recorder | null>(null);

  /**
   * Load recorders
   */
  async function loadRecorders() {
    isLoading = true;
    error = null;

    try {
      const response = await recorderApi.list({
        page,
        limit,
      });
      recorders = response.items;
      total = response.total;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to load recorders';
      }
    } finally {
      isLoading = false;
    }
  }

  // Load recorders on mount and when page changes
  $effect(() => {
    loadRecorders();
  });

  /**
   * Open create modal
   */
  function openCreateModal() {
    modalMode = 'create';
    editingRecorder = null;
    formData = {
      id: '',
      manufacturer: '',
      recorder_name: '',
      version: '',
    };
    showModal = true;
  }

  /**
   * Open edit modal
   */
  function openEditModal(recorder: Recorder) {
    modalMode = 'edit';
    editingRecorder = recorder;
    formData = {
      id: recorder.id,
      manufacturer: recorder.manufacturer,
      recorder_name: recorder.recorder_name,
      version: recorder.version || '',
    };
    showModal = true;
  }

  /**
   * Close modal
   */
  function closeModal() {
    showModal = false;
    editingRecorder = null;
    formData = {
      id: '',
      manufacturer: '',
      recorder_name: '',
      version: '',
    };
  }

  /**
   * Handle form submit
   */
  async function handleSubmit(event: Event) {
    event.preventDefault();
    error = null;

    try {
      if (modalMode === 'create') {
        const createData: RecorderCreateRequest = {
          id: formData.id.trim(),
          manufacturer: formData.manufacturer.trim(),
          recorder_name: formData.recorder_name.trim(),
          version: formData.version.trim() || undefined,
        };
        await recorderApi.create(createData);
        successMessage = 'Recorder created successfully';
      } else {
        const updateData: RecorderUpdateRequest = {
          manufacturer: formData.manufacturer.trim(),
          recorder_name: formData.recorder_name.trim(),
          version: formData.version.trim() || undefined,
        };
        await recorderApi.update(editingRecorder!.id, updateData);
        successMessage = 'Recorder updated successfully';
      }

      closeModal();
      await loadRecorders();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = `Failed to ${modalMode} recorder`;
      }
    }
  }

  /**
   * Open delete confirmation
   */
  function openDeleteConfirm(recorder: Recorder) {
    deleteConfirmRecorder = recorder;
  }

  /**
   * Close delete confirmation
   */
  function closeDeleteConfirm() {
    deleteConfirmRecorder = null;
  }

  /**
   * Delete recorder
   */
  async function handleDelete() {
    if (!deleteConfirmRecorder) return;

    error = null;

    try {
      await recorderApi.delete(deleteConfirmRecorder.id);
      successMessage = 'Recorder deleted successfully';
      closeDeleteConfirm();
      await loadRecorders();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to delete recorder';
      }
      closeDeleteConfirm();
    }
  }

  /**
   * Change page
   */
  function changePage(newPage: number) {
    page = newPage;
  }

  /**
   * Calculate total pages
   */
  const totalPages = $derived(Math.ceil(total / limit));

  /**
   * Format date
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString();
  }
</script>

<svelte:head>
  <title>Recorder Management - Admin - Echoroo</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-gray-900">Recorder Management</h1>
      <p class="mt-2 text-sm text-gray-600">Manage audio recorders and their metadata</p>
    </div>
    <button
      onclick={openCreateModal}
      class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
    >
      Add New Recorder
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

  <!-- Recorders Table -->
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
  {:else if recorders.length === 0}
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
          d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
        />
      </svg>
      <h3 class="mt-2 text-sm font-medium text-gray-900">No recorders found</h3>
      <p class="mt-1 text-sm text-gray-500">Get started by adding a new recorder.</p>
      <div class="mt-6">
        <button
          onclick={openCreateModal}
          class="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Add New Recorder
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
                Manufacturer
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Recorder Name
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Version
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
            {#each recorders as recorder (recorder.id)}
              <tr class="hover:bg-gray-50">
                <!-- ID -->
                <td class="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                  {recorder.id}
                </td>

                <!-- Manufacturer -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-900">
                  {recorder.manufacturer}
                </td>

                <!-- Recorder Name -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-900">
                  {recorder.recorder_name}
                </td>

                <!-- Version -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {recorder.version || '-'}
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {formatDate(recorder.created_at)}
                </td>

                <!-- Actions -->
                <td class="whitespace-nowrap px-6 py-4 text-sm">
                  <div class="flex gap-2">
                    <button
                      onclick={() => openEditModal(recorder)}
                      class="rounded bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-200"
                    >
                      Edit
                    </button>
                    <button
                      onclick={() => openDeleteConfirm(recorder)}
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

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="mt-6 flex items-center justify-between">
        <div class="text-sm text-gray-700">
          Showing <span class="font-medium">{(page - 1) * limit + 1}</span>
          to
          <span class="font-medium">{Math.min(page * limit, total)}</span>
          of
          <span class="font-medium">{total}</span>
          recorders
        </div>

        <div class="flex space-x-2">
          <button
            onclick={() => changePage(page - 1)}
            disabled={page === 1}
            class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Previous
          </button>

          {#each Array.from({ length: totalPages }, (_, i) => i + 1) as pageNum}
            {#if pageNum === 1 || pageNum === totalPages || (pageNum >= page - 1 && pageNum <= page + 1)}
              <button
                onclick={() => changePage(pageNum)}
                class="rounded-md px-4 py-2 text-sm font-medium {pageNum === page
                  ? 'bg-blue-600 text-white'
                  : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}"
              >
                {pageNum}
              </button>
            {:else if pageNum === page - 2 || pageNum === page + 2}
              <span class="px-2 text-gray-500">...</span>
            {/if}
          {/each}

          <button
            onclick={() => changePage(page + 1)}
            disabled={page === totalPages}
            class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    {/if}
  {/if}
</div>

<!-- Create/Edit Modal -->
{#if showModal}
  <div class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={closeModal}
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <form onsubmit={handleSubmit}>
          <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
            <div class="sm:flex sm:items-start">
              <div class="mt-3 w-full text-center sm:ml-0 sm:mt-0 sm:text-left">
                <h3 class="text-lg font-medium leading-6 text-gray-900" id="modal-title">
                  {modalMode === 'create' ? 'Add New Recorder' : 'Edit Recorder'}
                </h3>
                <div class="mt-4 space-y-4">
                  <!-- ID (only for create) -->
                  {#if modalMode === 'create'}
                    <div>
                      <label for="id" class="block text-sm font-medium text-gray-700">ID</label>
                      <input
                        type="text"
                        id="id"
                        bind:value={formData.id}
                        required
                        class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500 sm:text-sm"
                        placeholder="e.g., AUDIOMOTH_1.0.0"
                      />
                    </div>
                  {/if}

                  <!-- Manufacturer -->
                  <div>
                    <label for="manufacturer" class="block text-sm font-medium text-gray-700">Manufacturer</label>
                    <input
                      type="text"
                      id="manufacturer"
                      bind:value={formData.manufacturer}
                      required
                      class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500 sm:text-sm"
                      placeholder="e.g., Open Acoustic Devices"
                    />
                  </div>

                  <!-- Recorder Name -->
                  <div>
                    <label for="recorder_name" class="block text-sm font-medium text-gray-700">Recorder Name</label>
                    <input
                      type="text"
                      id="recorder_name"
                      bind:value={formData.recorder_name}
                      required
                      class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500 sm:text-sm"
                      placeholder="e.g., AudioMoth"
                    />
                  </div>

                  <!-- Version -->
                  <div>
                    <label for="version" class="block text-sm font-medium text-gray-700">Version (optional)</label>
                    <input
                      type="text"
                      id="version"
                      bind:value={formData.version}
                      class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500 sm:text-sm"
                      placeholder="e.g., 1.0.0"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
            <button
              type="submit"
              class="inline-flex w-full justify-center rounded-md bg-blue-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm"
            >
              {modalMode === 'create' ? 'Create' : 'Save'}
            </button>
            <button
              type="button"
              onclick={closeModal}
              class="mt-3 inline-flex w-full justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
{/if}

<!-- Delete Confirmation Modal -->
{#if deleteConfirmRecorder}
  <div class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={closeDeleteConfirm}
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-100 sm:mx-0 sm:h-10 sm:w-10">
              <svg
                class="h-6 w-6 text-red-600"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
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
                Delete Recorder
              </h3>
              <div class="mt-2">
                <p class="text-sm text-gray-500">
                  Are you sure you want to delete the recorder "{deleteConfirmRecorder.recorder_name}"
                  ({deleteConfirmRecorder.id})? This action cannot be undone.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleDelete}
            class="inline-flex w-full justify-center rounded-md bg-red-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm"
          >
            Delete
          </button>
          <button
            type="button"
            onclick={closeDeleteConfirm}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
