<script lang="ts">
  /**
   * Public project detail page — Phase 5 US1 (T210, polish round 4).
   *
   * Renders metadata for a Public + Active project to a Guest (or
   * authenticated) caller. Fetches the project + recording list via
   * TanStack Query against the Web UI surface (T200, T215) so the same
   * caching and retry semantics used elsewhere in the app apply.
   *
   * Privacy guarantees enforced here:
   *   - FR-018: 404 *and* 403 from the API are rendered as the same generic
   *     "not publicly available" message. The Web UI surface for Guests is
   *     supposed to collapse Restricted projects to 404 already, but if a
   *     future authenticated-but-non-member call reaches this page we keep
   *     enumeration safety by treating both statuses identically.
   *   - FR-030: raw lat/lng are never displayed; sites surface only via
   *     `h3_index` (the response shape itself does not currently include
   *     lat/lng for Guest callers, this is a defence-in-depth UI rule).
   *   - DL / Export / member CTAs are only rendered to *Guest* callers.
   *     Authenticated visitors land on the public detail page (e.g. via a
   *     shared link) and see a "Open in dashboard" link instead, so we do
   *     NOT show them a disabled-export tease that would imply Guest copy.
   *
   * Scope deferred to a later phase:
   *   - Map: not rendered here in MVP — the Web API contract for a Guest
   *     project response does not currently include a sites list with
   *     coordinates. We display project metadata only.
   */

  import { createQuery } from '@tanstack/svelte-query';
  import { ApiError, apiClient } from '$lib/api/client';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  // -------------------------------------------------------------------------
  // Local types — mirror the Phase 5 backend `ProjectResponse` shape
  // (apps/api/echoroo/schemas/project.py) which the global $lib/types entry
  // does not yet reflect (Phase 9 will resync). Defined locally so this file
  // stays self-contained and the type checker catches drift early.
  // -------------------------------------------------------------------------

  type ProjectVisibility = 'public' | 'restricted';
  type ProjectStatus = 'active' | 'dormant' | 'archived';

  interface PublicOwner {
    id: string;
    display_name: string | null;
  }

  interface PublicProject {
    id: string;
    name: string;
    description: string | null;
    visibility: ProjectVisibility;
    // Display license short_name (e.g. `CC-BY`), joined from the `licenses`
    // master on the response side. A plain string so admin-added licenses
    // (e.g. CC-BY-ND) render without a hardcoded short_name union.
    license: string;
    restricted_config: Record<string, unknown>;
    restricted_config_version: number;
    status: ProjectStatus;
    dormant_since: string | null;
    archived_since: string | null;
    owner: PublicOwner;
    created_at: string;
    updated_at: string;
  }

  interface PublicRecordingItem {
    /** Recording UUID. */
    id: string;
    /** Project UUID — needed for the audio stream URL. */
    project_id: string;
    /** Display name (filename or label). */
    name: string;
    /** Effective playback duration with time_expansion applied. */
    duration_seconds?: number | null;
    /** H3 cell index of the recording site, when available (FR-030). */
    site_h3_index?: string | null;
  }

  interface PublicRecordingListResponse {
    items: PublicRecordingItem[];
    total: number;
    page: number;
    limit: number;
  }

  // -------------------------------------------------------------------------
  // Props + query setup
  // -------------------------------------------------------------------------

  let { data } = $props();
  const projectId = $derived(data.projectId);
  const locale = $derived(getLocale());
  // Forwarded from `(public)/+layout.server.ts` so we can render
  // auth-aware UI without an extra round-trip. Authenticated visitors who
  // land on this public page should NOT see the Guest-only sign-in CTA.
  const isAuthenticated = $derived<boolean>(data.isAuthenticated ?? false);

  // Cache key includes locale per project memory rule (TanStack Query keys
  // include locale for cache separation across language switches).
  const projectQuery = $derived(
    createQuery<PublicProject, ApiError>({
      queryKey: ['public-project', projectId, locale],
      queryFn: () =>
        apiClient.get<PublicProject>(`/web-api/v1/projects/${projectId}`),
      enabled: !!projectId,
      retry: false,
    })
  );

  const project = $derived($projectQuery.data ?? null);
  const isLoading = $derived($projectQuery.isLoading);
  const queryError = $derived($projectQuery.error);

  // -------------------------------------------------------------------------
  // Recordings — Phase 5 polish round 4 (致命 1).
  //
  // The Web UI surface `GET /web-api/v1/projects/{id}/recordings` (T215) is
  // Guest-aware and reuses the same enumeration-safety semantics as
  // `GET /web-api/v1/projects/{id}` (Restricted projects → 404 / FR-018).
  // We only kick the recording query off once the project query has
  // succeeded — that way a 404 on the project never produces a stray 404
  // on the recording fetch (and avoids two simultaneous error toasts).
  // -------------------------------------------------------------------------
  const recordingsQuery = $derived(
    createQuery<PublicRecordingListResponse, ApiError>({
      queryKey: ['public-project-recordings', projectId, locale],
      queryFn: () =>
        apiClient.get<PublicRecordingListResponse>(
          `/web-api/v1/projects/${projectId}/recordings?limit=50`
        ),
      // Wait for the project query to land so a 404/403 on the project
      // surface does not trigger a duplicate request that would only
      // produce another generic error.
      enabled: !!projectId && !!project,
      retry: false,
    })
  );
  const recordings = $derived<PublicRecordingItem[]>(
    $recordingsQuery.data?.items ?? []
  );
  const recordingsLoading = $derived($recordingsQuery.isLoading);
  const recordingsError = $derived($recordingsQuery.error);

  /**
   * Build the audio stream URL for a recording. The endpoint
   * (/api/v1/projects/{pid}/recordings/{rid}/audio) gates on VIEW_MEDIA which
   * is granted to Guests on Public + Active projects via the canonical
   * matrix (FR-016). Authentication is therefore optional.
   */
  function buildAudioUrl(rec: PublicRecordingItem): string {
    return `/api/v1/projects/${rec.project_id}/recordings/${rec.id}/audio`;
  }

  // Track which recording is currently selected for playback so we can
  // mount a single `<audio>` element rather than N concurrent ones.
  let activeRecordingId = $state<string | null>(null);
  const activeRecording = $derived(
    recordings.find((r) => r.id === activeRecordingId) ?? null
  );

  function playRecording(id: string) {
    activeRecordingId = id;
  }

  // -------------------------------------------------------------------------
  // Error normalisation
  //
  // FR-018: a 404 (or 403, see below) returned by the backend may correspond
  // to "the project never existed", "the project is Restricted/Archived",
  // or — for an authenticated non-member — "the project exists but you may
  // not read it". The Web UI for a Guest-aware endpoint should collapse all
  // three into the same generic "not publicly available" copy so callers
  // cannot probe project existence by attempting to load a UUID.
  //
  // Polish round 4 (重要 2): the previous implementation only normalised 404,
  // which meant a stray 403 from `/web-api/v1/projects/{id}` (e.g. an
  // authenticated visitor hitting a Restricted project they are NOT a
  // member of) would render a "generic error" with the API detail string —
  // that is an enumeration leak. We now treat 403 the same as 404.
  //
  // 401 (auth expired) and 5xx are kept as separate branches so the user
  // gets actionable feedback (sign-in CTA / "try again later") instead of
  // being silently misled.
  // -------------------------------------------------------------------------

  const errorState = $derived.by<
    | { kind: 'not_available' }
    | { kind: 'unauthenticated' }
    | { kind: 'generic'; message: string }
    | null
  >(() => {
    if (!queryError) return null;
    if (queryError instanceof ApiError) {
      // 404 (resource missing or Guest-hidden) and 403 (matrix-denied) both
      // collapse to the same anti-enumeration copy.
      if (queryError.status === 404 || queryError.status === 403) {
        return { kind: 'not_available' };
      }
      if (queryError.status === 401) return { kind: 'unauthenticated' };
      return {
        kind: 'generic',
        message: queryError.detail || queryError.message,
      };
    }
    return {
      kind: 'generic',
      message: m.public_project_detail_error_load(),
    };
  });

  // -------------------------------------------------------------------------
  // Format helpers
  // -------------------------------------------------------------------------

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString(locale);
    } catch {
      return iso;
    }
  }

  function visibilityLabel(v: ProjectVisibility): string {
    return v === 'public'
      ? m.public_project_detail_visibility_public()
      : m.public_project_detail_visibility_restricted();
  }

  function statusLabel(s: ProjectStatus): string {
    if (s === 'active') return m.public_project_detail_status_active();
    if (s === 'dormant') return m.public_project_detail_status_dormant();
    return m.public_project_detail_status_archived();
  }
</script>

<svelte:head>
  <title>{project ? project.name : m.public_project_detail_loading()} - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
  {#if isLoading}
    <!-- Loading state -->
    <div class="flex items-center justify-center py-12" aria-live="polite">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
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
      <span class="sr-only">{m.public_project_detail_loading()}</span>
    </div>
  {:else if errorState?.kind === 'not_available'}
    <!-- FR-018: generic copy for 404, do not leak existence -->
    <div class="rounded-md bg-stone-50 p-6 text-center" role="alert">
      <h1 class="mb-2 text-lg font-semibold text-stone-900">
        {m.public_project_detail_unavailable_title()}
      </h1>
      <p class="text-sm text-stone-600">
        {m.public_project_detail_unavailable_body()}
      </p>
      <div class="mt-6">
        <a
          href={localizeHref('/explore/projects')}
          class="text-sm font-medium text-primary-600 hover:text-primary-500"
        >
          {m.public_project_detail_back_to_explore()}
        </a>
      </div>
    </div>
  {:else if errorState?.kind === 'unauthenticated'}
    <!-- 401 should not happen for a Guest path, but if the API ever
         disagrees, surface a sign-in CTA rather than a generic error. -->
    <div class="rounded-md bg-stone-50 p-6 text-center" role="alert">
      <h1 class="mb-2 text-lg font-semibold text-stone-900">
        {m.public_project_detail_signin_required_title()}
      </h1>
      <p class="mb-4 text-sm text-stone-600">
        {m.public_project_detail_signin_required_body()}
      </p>
      <a
        href={localizeHref('/login')}
        class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700"
      >
        {m.auth_login_submit()}
      </a>
    </div>
  {:else if errorState?.kind === 'generic'}
    <div class="rounded-md bg-danger-light p-4" role="alert">
      <p class="text-sm font-medium text-danger">{errorState.message}</p>
    </div>
  {:else if project}
    <!-- Project header -->
    <header class="mb-8">
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <span
          class="inline-flex items-center rounded-full bg-success-light px-3 py-1 text-xs font-medium text-success"
          aria-label={visibilityLabel(project.visibility)}
        >
          {visibilityLabel(project.visibility)}
        </span>
        <span
          class="inline-flex items-center rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-800 dark:bg-stone-700 dark:text-stone-200"
        >
          {statusLabel(project.status)}
        </span>
        <span
          class="inline-flex items-center rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-800 dark:bg-stone-700 dark:text-stone-200"
          aria-label={m.public_project_detail_license_label({ license: project.license })}
        >
          {project.license}
        </span>
      </div>
      <h1 class="text-3xl font-bold text-stone-900">{project.name}</h1>
      <p class="mt-2 text-sm text-stone-600">
        {m.public_project_detail_byline({
          owner: project.owner.display_name ?? m.public_project_detail_owner_anonymous(),
          date: formatDate(project.created_at),
        })}
      </p>
    </header>

    <!-- Description -->
    <section class="mb-6 rounded-lg bg-surface-card p-6 shadow">
      <h2 class="mb-3 text-lg font-semibold text-stone-900">
        {m.public_project_detail_description_heading()}
      </h2>
      {#if project.description}
        <p class="whitespace-pre-wrap text-sm text-stone-700">{project.description}</p>
      {:else}
        <p class="text-sm italic text-stone-400">
          {m.public_project_detail_no_description()}
        </p>
      {/if}
    </section>

    <!-- Recordings -->
    <section class="mb-6 rounded-lg bg-surface-card p-6 shadow">
      <h2 class="mb-3 text-lg font-semibold text-stone-900">
        {m.public_project_detail_recordings_heading()}
      </h2>

      {#if recordingsLoading}
        <p class="text-sm italic text-stone-500" aria-live="polite">
          {m.public_project_detail_loading()}
        </p>
      {:else if recordingsError}
        <!-- A failure to load the recording list is non-fatal — the project
             page itself stays useful. Surface a generic message; details
             would only encourage probing. -->
        <p class="text-sm italic text-stone-500">
          {m.public_project_detail_recordings_unavailable()}
        </p>
      {:else if recordings.length === 0}
        <p class="text-sm italic text-stone-500">
          {m.public_project_detail_recordings_unavailable()}
        </p>
      {:else}
        <ul class="space-y-2">
          {#each recordings as rec (rec.id)}
            <li
              class="flex items-center justify-between rounded-md border border-stone-200 p-3 dark:border-stone-700"
            >
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-stone-900">{rec.name}</p>
                {#if rec.site_h3_index}
                  <!-- FR-030: only the H3 cell index is displayed, never raw lat/lng -->
                  <p class="mt-0.5 text-xs text-stone-500">
                    {m.public_project_detail_recording_site_h3({ h3: rec.site_h3_index })}
                  </p>
                {/if}
              </div>
              <button
                type="button"
                onclick={() => playRecording(rec.id)}
                class="ml-3 inline-flex items-center rounded-md bg-primary-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-primary-700"
              >
                {m.public_project_detail_play_button()}
              </button>
            </li>
          {/each}
        </ul>

        {#if activeRecording}
          <div class="mt-4 rounded-md bg-stone-50 p-3 dark:bg-stone-800">
            <p class="mb-2 text-xs text-stone-600">
              {m.public_project_detail_now_playing({ name: activeRecording.name })}
            </p>
            <!-- The endpoint streams via Range with the canonical matrix
                 granting VIEW_MEDIA to Guests on Public + Active projects. -->
            <audio
              controls
              preload="metadata"
              src={buildAudioUrl(activeRecording)}
              class="w-full"
              aria-label={m.public_project_detail_audio_label({ name: activeRecording.name })}
            >
              <track kind="captions" />
            </audio>
          </div>
        {/if}
      {/if}
    </section>

    {#if !isAuthenticated}
      <!-- Guest-only notice: download/export disabled. Authenticated callers
           who land here (e.g. via a shared public link) MUST NOT see the
           "sign in to enable export" copy — they are already signed in. -->
      <section class="mb-6 rounded-lg border border-dashed border-stone-300 p-4 text-sm">
        <div class="flex items-start gap-3">
          <svg
            class="mt-0.5 h-5 w-5 flex-shrink-0 text-stone-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <div class="flex-1">
            <p class="font-medium text-stone-900">
              {m.public_project_detail_signin_for_more_title()}
            </p>
            <p class="mt-1 text-stone-600">
              {m.public_project_detail_signin_for_more_body()}
            </p>
            <div class="mt-3 flex items-center gap-3">
              <button
                type="button"
                disabled
                aria-disabled="true"
                class="inline-flex items-center rounded-md bg-stone-200 px-3 py-1.5 text-xs font-medium text-stone-500 cursor-not-allowed"
                title={m.public_project_detail_export_disabled_tooltip()}
              >
                {m.public_project_detail_export_button_disabled()}
              </button>
              <a
                href={localizeHref('/login')}
                class="text-xs font-medium text-primary-600 hover:text-primary-500"
              >
                {m.public_project_detail_signin_link()}
              </a>
            </div>
          </div>
        </div>
      </section>
    {:else}
      <!-- Authenticated visitor on the public page — surface a quick link
           into the project's full app surface. The (app) layer re-enforces
           access on the server side, so a non-member who follows this link
           will simply be denied there. We deliberately link directly to the
           project rather than the generic dashboard so the visitor lands on
           the same context they were just viewing. -->
      <section class="mb-6 text-sm">
        <a
          href={localizeHref(`/projects/${projectId}`)}
          class="inline-flex items-center text-xs font-medium text-primary-600 hover:text-primary-500"
        >
          {m.public_project_detail_open_in_app()}
        </a>
      </section>
    {/if}
  {/if}
</div>
