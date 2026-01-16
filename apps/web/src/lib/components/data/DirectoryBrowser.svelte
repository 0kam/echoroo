<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchDirectories } from '$lib/api/datasets';

  export let onSelect: (path: string) => void;
  export let selectedPath: string = '';

  let currentPath = '';
  let pathHistory: string[] = [];

  $: directoriesQuery = createQuery({
    queryKey: ['directories', currentPath],
    queryFn: () => fetchDirectories(currentPath || undefined),
  });

  function navigateTo(path: string) {
    if (currentPath) {
      pathHistory = [...pathHistory, currentPath];
    }
    currentPath = path;
  }

  function goBack() {
    if (pathHistory.length > 0) {
      const lastPath = pathHistory[pathHistory.length - 1];
      currentPath = lastPath ?? '';
      pathHistory = pathHistory.slice(0, -1);
    } else {
      currentPath = '';
    }
  }

  function goToRoot() {
    pathHistory = [];
    currentPath = '';
  }

  function selectDirectory(path: string) {
    onSelect(path);
  }

  function getBreadcrumbs(): string[] {
    if (!currentPath) return [];
    return currentPath.split('/').filter((p) => p);
  }

  function navigateToBreadcrumb(index: number) {
    const parts = currentPath.split('/').filter((p) => p);
    const newPath = '/' + parts.slice(0, index + 1).join('/');
    currentPath = newPath;
    pathHistory = [];
  }
</script>

<div class="directory-browser">
  <!-- Breadcrumb navigation -->
  <div class="breadcrumb">
    <button class="breadcrumb-item" on:click={goToRoot}>
      <span class="home-icon">🏠</span>
      Root
    </button>
    {#each getBreadcrumbs() as crumb, index}
      <span class="separator">/</span>
      <button class="breadcrumb-item" on:click={() => navigateToBreadcrumb(index)}>
        {crumb}
      </button>
    {/each}
  </div>

  <!-- Navigation controls -->
  <div class="controls">
    <button class="control-btn" on:click={goBack} disabled={pathHistory.length === 0}>
      ← Back
    </button>
    <div class="current-path">
      <span class="path-label">Current path:</span>
      <code>{$directoriesQuery.data?.path || '/'}</code>
    </div>
  </div>

  <!-- Directory list -->
  <div class="directory-list">
    {#if $directoriesQuery.isLoading}
      <div class="loading">Loading directories...</div>
    {:else if $directoriesQuery.isError}
      <div class="error">Error: {$directoriesQuery.error?.message}</div>
    {:else if $directoriesQuery.data}
      {#if $directoriesQuery.data.directories.length === 0}
        <div class="empty">No subdirectories found</div>
      {:else}
        <ul>
          {#each $directoriesQuery.data.directories as dir}
            <li class="directory-item" class:selected={selectedPath === dir.path}>
              <button class="directory-name" on:click={() => navigateTo(dir.path)}>
                <span class="folder-icon">📁</span>
                <span class="name">{dir.name}</span>
              </button>

              <div class="directory-info">
                {#if dir.audio_file_count > 0}
                  <span class="file-count">
                    {dir.audio_file_count} audio file{dir.audio_file_count !== 1 ? 's' : ''}
                  </span>
                  {#if dir.formats.length > 0}
                    <span class="formats">({dir.formats.join(', ')})</span>
                  {/if}
                {/if}
                <button class="select-btn" on:click={() => selectDirectory(dir.path)}>
                  Select
                </button>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </div>

  <!-- Selected path display -->
  {#if selectedPath}
    <div class="selected-info">
      <span class="selected-label">Selected:</span>
      <code>{selectedPath}</code>
    </div>
  {/if}
</div>

<style>
  .directory-browser {
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    overflow: hidden;
  }

  .breadcrumb {
    display: flex;
    align-items: center;
    padding: 0.75rem;
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
    overflow-x: auto;
    white-space: nowrap;
  }

  .breadcrumb-item {
    padding: 0.25rem 0.5rem;
    background: none;
    border: none;
    color: #3b82f6;
    font-size: 0.875rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .breadcrumb-item:hover {
    text-decoration: underline;
  }

  .home-icon {
    font-size: 1rem;
  }

  .separator {
    margin: 0 0.25rem;
    color: #9ca3af;
  }

  .controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem;
    background: white;
    border-bottom: 1px solid #e5e7eb;
  }

  .control-btn {
    padding: 0.375rem 0.75rem;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    cursor: pointer;
  }

  .control-btn:hover:not(:disabled) {
    background: #f9fafb;
  }

  .control-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .current-path {
    font-size: 0.875rem;
  }

  .path-label {
    color: #6b7280;
    margin-right: 0.5rem;
  }

  .current-path code {
    background: #f3f4f6;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-family: monospace;
  }

  .directory-list {
    max-height: 400px;
    overflow-y: auto;
  }

  .loading,
  .error,
  .empty {
    padding: 2rem;
    text-align: center;
    color: #6b7280;
  }

  .error {
    color: #dc2626;
  }

  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .directory-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem;
    border-bottom: 1px solid #e5e7eb;
    transition: background 0.15s ease;
  }

  .directory-item:hover {
    background: #f9fafb;
  }

  .directory-item.selected {
    background: #eff6ff;
  }

  .directory-name {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font-size: 0.875rem;
    color: #111827;
  }

  .directory-name:hover .name {
    color: #3b82f6;
  }

  .folder-icon {
    font-size: 1.25rem;
  }

  .name {
    font-weight: 500;
  }

  .directory-info {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.75rem;
  }

  .file-count {
    color: #6b7280;
  }

  .formats {
    color: #9ca3af;
  }

  .select-btn {
    padding: 0.25rem 0.625rem;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    cursor: pointer;
  }

  .select-btn:hover {
    background: #2563eb;
  }

  .selected-info {
    padding: 0.75rem;
    background: #f0fdf4;
    border-top: 1px solid #bbf7d0;
    font-size: 0.875rem;
  }

  .selected-label {
    font-weight: 500;
    color: #065f46;
    margin-right: 0.5rem;
  }

  .selected-info code {
    background: white;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-family: monospace;
    color: #065f46;
  }
</style>
