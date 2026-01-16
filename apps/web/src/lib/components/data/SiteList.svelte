<script lang="ts">
  import type { Site } from '$lib/types/data';

  export let sites: Site[] = [];
  export let onSelect: (site: Site) => void = () => {};
  export let onDelete: (site: Site) => void = () => {};
  export let selectedId: string | null = null;

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }
</script>

<div class="site-list">
  {#if sites.length === 0}
    <div class="empty-state">
      <p>No sites found. Create your first site to get started.</p>
    </div>
  {:else}
    <ul>
      {#each sites as site (site.id)}
        <li
          class="site-item"
          class:selected={site.id === selectedId}
          role="button"
          tabindex="0"
          on:click={() => onSelect(site)}
          on:keydown={(e) => e.key === 'Enter' && onSelect(site)}
        >
          <div class="site-info">
            <h3>{site.name}</h3>
            <p class="h3-index">
              <code>{site.h3_index}</code>
            </p>
            <p class="date">Created: {formatDate(site.created_at)}</p>
          </div>
          <div class="site-actions">
            <button
              class="delete-btn"
              on:click|stopPropagation={() => onDelete(site)}
              aria-label="Delete site"
            >
              Delete
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .site-list {
    width: 100%;
  }

  .empty-state {
    padding: 2rem;
    text-align: center;
    color: #6b7280;
    background: #f9fafb;
    border-radius: 0.5rem;
  }

  ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .site-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .site-item:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  .site-item.selected {
    background: #eff6ff;
    border-color: #3b82f6;
  }

  .site-info h3 {
    margin: 0 0 0.25rem 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .h3-index {
    margin: 0 0 0.25rem 0;
    font-size: 0.75rem;
    color: #6b7280;
  }

  .h3-index code {
    background: #f3f4f6;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    font-family: monospace;
  }

  .date {
    margin: 0;
    font-size: 0.75rem;
    color: #9ca3af;
  }

  .delete-btn {
    padding: 0.375rem 0.75rem;
    font-size: 0.75rem;
    color: #dc2626;
    background: white;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .delete-btn:hover {
    background: #fef2f2;
    border-color: #f87171;
  }
</style>
