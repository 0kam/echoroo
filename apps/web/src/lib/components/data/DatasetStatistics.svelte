<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchDatasetStatistics } from '$lib/api/datasets';

  export let projectId: string;
  export let datasetId: string;

  $: statsQuery = createQuery({
    queryKey: ['dataset-statistics', projectId, datasetId],
    queryFn: () => fetchDatasetStatistics(projectId, datasetId),
  });

  function formatDuration(seconds: number): string {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`;
    } else if (minutes > 0) {
      return `${minutes}m ${secs}s`;
    } else {
      return `${secs}s`;
    }
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }

  function getMaxValue(obj: Record<string | number, number>): number {
    return Math.max(...Object.values(obj), 1);
  }
</script>

<div class="dataset-statistics">
  <h3>Statistics</h3>

  {#if $statsQuery.isLoading}
    <div class="loading">Loading statistics...</div>
  {:else if $statsQuery.isError}
    <div class="error">Error: {$statsQuery.error?.message}</div>
  {:else if $statsQuery.data}
    {@const stats = $statsQuery.data}

    <!-- Summary cards -->
    <div class="stats-cards">
      <div class="stat-card">
        <div class="stat-label">Recordings</div>
        <div class="stat-value">{stats.recording_count.toLocaleString()}</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Total Duration</div>
        <div class="stat-value">{formatDuration(stats.total_duration)}</div>
      </div>

      {#if stats.date_range}
        <div class="stat-card">
          <div class="stat-label">Date Range</div>
          <div class="stat-value-small">
            {formatDate(stats.date_range.start)}
            <br />
            to
            <br />
            {formatDate(stats.date_range.end)}
          </div>
        </div>
      {/if}
    </div>

    <!-- Distributions -->
    <div class="distributions">
      <!-- Sample rate distribution -->
      {#if Object.keys(stats.samplerate_distribution).length > 0}
        <div class="distribution-section">
          <h4>Sample Rates</h4>
          <div class="bar-chart">
            {#each Object.entries(stats.samplerate_distribution) as [samplerate, count]}
              {@const maxCount = getMaxValue(stats.samplerate_distribution)}
              {@const percentage = (count / maxCount) * 100}
              <div class="bar-item">
                <div class="bar-label">{parseInt(samplerate).toLocaleString()} Hz</div>
                <div class="bar-container">
                  <div class="bar-fill" style="width: {percentage}%" />
                  <span class="bar-count">{count.toLocaleString()}</span>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Format distribution -->
      {#if Object.keys(stats.format_distribution).length > 0}
        <div class="distribution-section">
          <h4>File Formats</h4>
          <div class="bar-chart">
            {#each Object.entries(stats.format_distribution) as [format, count]}
              {@const maxCount = getMaxValue(stats.format_distribution)}
              {@const percentage = (count / maxCount) * 100}
              <div class="bar-item">
                <div class="bar-label">{format.toUpperCase()}</div>
                <div class="bar-container">
                  <div class="bar-fill" style="width: {percentage}%" />
                  <span class="bar-count">{count.toLocaleString()}</span>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>

    <!-- Recordings by date -->
    {#if stats.recordings_by_date.length > 0}
      {@const maxCount = Math.max(...stats.recordings_by_date.map((d) => d.count), 1)}
      <div class="timeline-section">
        <h4>Recordings by Date</h4>
        <div class="timeline-chart">
          {#each stats.recordings_by_date.slice(0, 30) as dateData}
            {@const percentage = (dateData.count / maxCount) * 100}
            <div class="timeline-item" title="{formatDate(dateData.date)}: {dateData.count} recording(s)">
              <div class="timeline-bar" style="height: {percentage}%" />
              <div class="timeline-label">{formatDate(dateData.date)}</div>
            </div>
          {/each}
        </div>
        {#if stats.recordings_by_date.length > 30}
          <p class="chart-note">Showing first 30 days</p>
        {/if}
      </div>
    {/if}

    <!-- Recordings by hour -->
    {#if stats.recordings_by_hour.length > 0}
      {@const maxCount = Math.max(...stats.recordings_by_hour.map((h) => h.count), 1)}
      <div class="hourly-section">
        <h4>Recordings by Hour of Day</h4>
        <div class="hourly-chart">
          {#each stats.recordings_by_hour as hourData}
            {@const percentage = (hourData.count / maxCount) * 100}
            <div class="hourly-item">
              <div class="hourly-bar" style="height: {percentage}%" title="{hourData.hour}:00 - {hourData.count} recording(s)" />
              <div class="hourly-label">{hourData.hour}</div>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .dataset-statistics {
    padding: 1.5rem;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  h3 {
    margin: 0 0 1.5rem 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  h4 {
    margin: 0 0 1rem 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
  }

  .loading,
  .error {
    padding: 2rem;
    text-align: center;
    color: #6b7280;
  }

  .error {
    color: #dc2626;
  }

  .stats-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }

  .stat-card {
    padding: 1rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
  }

  .stat-label {
    font-size: 0.75rem;
    color: #6b7280;
    margin-bottom: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .stat-value {
    font-size: 1.5rem;
    font-weight: 600;
    color: #111827;
  }

  .stat-value-small {
    font-size: 0.875rem;
    font-weight: 500;
    color: #111827;
    line-height: 1.4;
  }

  .distributions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 2rem;
    margin-bottom: 2rem;
  }

  .distribution-section {
    padding: 1rem;
    background: #f9fafb;
    border-radius: 0.375rem;
  }

  .bar-chart {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .bar-item {
    display: grid;
    grid-template-columns: 80px 1fr;
    gap: 0.75rem;
    align-items: center;
  }

  .bar-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #374151;
    text-align: right;
  }

  .bar-container {
    position: relative;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .bar-fill {
    height: 1.5rem;
    background: #3b82f6;
    border-radius: 0.25rem;
    min-width: 2px;
    transition: width 0.3s ease;
  }

  .bar-count {
    font-size: 0.75rem;
    color: #6b7280;
    white-space: nowrap;
  }

  .timeline-section,
  .hourly-section {
    margin-bottom: 2rem;
  }

  .timeline-chart {
    display: flex;
    gap: 0.25rem;
    height: 150px;
    align-items: flex-end;
    padding: 0.5rem;
    background: #f9fafb;
    border-radius: 0.375rem;
    overflow-x: auto;
  }

  .timeline-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 50px;
  }

  .timeline-bar {
    width: 100%;
    background: #3b82f6;
    border-radius: 0.25rem 0.25rem 0 0;
    min-height: 2px;
    transition: height 0.3s ease;
  }

  .timeline-label {
    margin-top: 0.5rem;
    font-size: 0.625rem;
    color: #6b7280;
    writing-mode: vertical-rl;
    text-orientation: mixed;
  }

  .hourly-chart {
    display: grid;
    grid-template-columns: repeat(24, 1fr);
    gap: 0.25rem;
    height: 120px;
    align-items: flex-end;
    padding: 0.5rem;
    background: #f9fafb;
    border-radius: 0.375rem;
  }

  .hourly-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 100%;
  }

  .hourly-bar {
    width: 100%;
    background: #10b981;
    border-radius: 0.25rem 0.25rem 0 0;
    min-height: 2px;
    transition: height 0.3s ease;
    cursor: pointer;
  }

  .hourly-bar:hover {
    background: #059669;
  }

  .hourly-label {
    margin-top: auto;
    padding-top: 0.25rem;
    font-size: 0.625rem;
    color: #6b7280;
  }

  .chart-note {
    margin: 0.5rem 0 0 0;
    font-size: 0.75rem;
    color: #6b7280;
    font-style: italic;
  }
</style>
