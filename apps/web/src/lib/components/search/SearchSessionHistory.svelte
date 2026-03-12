<script lang="ts">
  /**
   * SearchSessionHistory - Collapsible panel listing past search sessions.
   *
   * Shows session name, status, date, species count, and result/confirmed/rejected
   * counts. Allows clicking a session to load its results, and deleting sessions
   * with confirmation.
   */

  import * as m from '$lib/paraglide/messages';
  import type { SearchSessionListItem } from '$lib/types/search';
  import { listSearchSessions, deleteSearchSession } from '$lib/api/search';

  interface Props {
    projectId: string;
    onSelectSession: (sessionId: string) => void;
    activeSessionId?: string;
    /** Increment to trigger a refresh of the session list. */
    refreshTrigger?: number;
  }

  let { projectId, onSelectSession, activeSessionId, refreshTrigger = 0 }: Props = $props();

  let sessions = $state<SearchSessionListItem[]>([]);
  let isLoading = $state(true);
  let isExpanded = $state(true);
  let deletingId = $state<string | null>(null);

  async function loadSessions() {
    isLoading = true;
    try {
      const response = await listSearchSessions(projectId);
      sessions = response.sessions;
    } catch (e) {
      console.error('Failed to load sessions:', e);
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    // Re-run when refreshTrigger changes
    void refreshTrigger;
    loadSessions();
  });

  async function handleDelete(e: Event, sessionId: string) {
    e.stopPropagation();
    if (!confirm(m.search_session_delete_confirm())) return;
    deletingId = sessionId;
    try {
      await deleteSearchSession(projectId, sessionId);
      sessions = sessions.filter((s) => s.id !== sessionId);
    } catch (e) {
      console.error('Failed to delete session:', e);
    } finally {
      deletingId = null;
    }
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function getStatusColor(status: string): string {
    switch (status) {
      case 'completed':
        return 'text-green-600';
      case 'running':
        return 'text-primary-500';
      case 'failed':
        return 'text-red-500';
      default:
        return 'text-stone-400';
    }
  }

  function getStatusIcon(status: string): string {
    switch (status) {
      case 'completed':
        return '●';
      case 'running':
        return '◌';
      case 'failed':
        return '✕';
      default:
        return '○';
    }
  }

  function getSpeciesCount(session: SearchSessionListItem): number {
    return session.species_config?.length ?? 0;
  }

  function getSpeciesNames(session: SearchSessionListItem): string {
    const config = session.species_config;
    if (!config || config.length === 0) return '';
    const names = config.map((s) => s.common_name ?? s.scientific_name);
    if (names.length <= 2) return names.join(', ');
    return `${names.slice(0, 2).join(', ')} +${names.length - 2}`;
  }
</script>

<div class="rounded-lg border border-card bg-surface-card shadow-sm">
  <!-- Panel header -->
  <button
    type="button"
    class="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-stone-50"
    onclick={() => { isExpanded = !isExpanded; }}
    aria-expanded={isExpanded}
  >
    <div class="flex items-center gap-2">
      <!-- History icon -->
      <svg class="h-4 w-4 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <span class="text-sm font-semibold text-stone-700">{m.search_sessions()}</span>
      {#if !isLoading && sessions.length > 0}
        <span class="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-500">
          {sessions.length}
        </span>
      {/if}
    </div>
    <!-- Chevron icon -->
    <svg
      class="h-4 w-4 text-stone-400 transition-transform {isExpanded ? 'rotate-180' : ''}"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      stroke-width="2"
      aria-hidden="true"
    >
      <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  </button>

  {#if isExpanded}
    <div class="border-t border-card">
      {#if isLoading}
        <!-- Loading skeleton -->
        <div class="space-y-2 p-3">
          {#each { length: 3 } as _}
            <div class="h-12 animate-pulse rounded-md bg-stone-100"></div>
          {/each}
        </div>
      {:else if sessions.length === 0}
        <!-- Empty state -->
        <div class="flex flex-col items-center justify-center py-8 text-center">
          <svg class="mb-2 h-8 w-8 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p class="text-sm text-stone-400">{m.search_sessions_empty()}</p>
        </div>
      {:else}
        <!-- Session list -->
        <ul class="divide-y divide-stone-100">
          {#each sessions as session (session.id)}
            {@const isActive = session.id === activeSessionId}
            <li
              class="group relative transition-colors
                {isActive
                  ? 'bg-primary-50 hover:bg-primary-100'
                  : 'hover:bg-stone-50'}"
            >
              <!-- Clickable row area (keyboard/mouse accessible) -->
              <div
                role="button"
                tabindex="0"
                class="flex w-full cursor-pointer items-start gap-3 px-4 py-3 pr-10 text-left"
                onclick={() => onSelectSession(session.id)}
                onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelectSession(session.id); } }}
                aria-pressed={isActive}
              >
                <!-- Status indicator -->
                <span
                  class="mt-0.5 shrink-0 text-sm leading-none {getStatusColor(session.status)}"
                  title={session.status}
                  aria-label={session.status}
                >
                  {getStatusIcon(session.status)}
                </span>

                <!-- Session info -->
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="truncate text-sm font-medium {isActive ? 'text-primary-800' : 'text-stone-800'}">
                      {(session.name ?? getSpeciesNames(session)) || session.id.slice(0, 8)}
                    </span>
                    {#if getSpeciesCount(session) > 0}
                      <span class="shrink-0 rounded-full bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
                        {getSpeciesCount(session)} sp
                      </span>
                    {/if}
                  </div>
                  <div class="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-stone-400">
                    <span>{formatDate(session.created_at)}</span>
                    {#if session.result_count > 0}
                      <span class="text-stone-300" aria-hidden="true">·</span>
                      <span>{m.search_results_count_session({ count: String(session.result_count) })}</span>
                    {/if}
                    {#if session.confirmed_count > 0}
                      <span class="text-green-600">
                        {m.search_confirmed_count({ count: String(session.confirmed_count) })}
                      </span>
                    {/if}
                    {#if session.rejected_count > 0}
                      <span class="text-red-500">
                        {m.search_rejected_count({ count: String(session.rejected_count) })}
                      </span>
                    {/if}
                  </div>
                </div>
              </div>

              <!-- Delete button (visible on hover, positioned absolutely) -->
              <button
                type="button"
                class="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-stone-300 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100 focus:opacity-100"
                onclick={(e) => handleDelete(e, session.id)}
                disabled={deletingId === session.id}
                aria-label={m.search_session_delete()}
              >
                {#if deletingId === session.id}
                  <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                {:else}
                  <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                  </svg>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>
