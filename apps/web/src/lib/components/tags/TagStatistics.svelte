<script lang="ts">
  /**
   * TagStatistics — usage-count cards for the project's tags.
   *
   * Extracted from the tag settings page. Renders nothing when there are no
   * statistics, matching the original page's guard.
   */
  import * as m from '$lib/paraglide/messages';
  import type { TagStatistic } from '$lib/types/tag';
  import { getCategoryLabel } from './categoryLabel';

  interface Props {
    stats: TagStatistic[];
  }

  const { stats }: Props = $props();
</script>

{#if stats.length > 0}
  <div class="statistics-section">
    <h2>{m.annotation_tag_stats_title()}</h2>
    <div class="statistics-grid">
      {#each stats as stat}
        <div class="stat-card">
          <div class="stat-card__name">{stat.tag.name}</div>
          <div class="stat-card__meta">
            <span class="category-badge category-badge--{stat.tag.category}">
              {getCategoryLabel(stat.tag.category)}
            </span>
          </div>
          <div class="stat-card__count">{m.annotation_tag_stats_uses({ count: stat.usage_count })}</div>
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .statistics-section {
    margin-top: 2.5rem;
    padding-top: 2rem;
    border-top: 1px solid #e5e7eb;
  }

  .statistics-section h2 {
    margin: 0 0 1.25rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .statistics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1rem;
  }

  .stat-card {
    background: rgb(var(--color-card-bg));
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .stat-card__name {
    font-weight: 500;
    color: #111827;
    font-size: 0.875rem;
  }

  .stat-card__meta {
    display: flex;
    gap: 0.375rem;
  }

  .stat-card__count {
    font-size: 1.25rem;
    font-weight: 600;
    color: rgb(var(--primary-500));
    margin-top: 0.25rem;
  }

  /* Category badges */
  .category-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 500;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
  }

  .category-badge--species {
    background: #dcfce7;
    color: #166534;
  }

  .category-badge--sound_type {
    background: #dbeafe;
    color: #1e40af;
  }

  .category-badge--quality {
    background: #fef9c3;
    color: #854d0e;
  }
</style>
