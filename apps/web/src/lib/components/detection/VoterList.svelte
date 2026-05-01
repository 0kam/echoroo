<script lang="ts">
  /**
   * VoterList - Detail-view list of individual voters on an annotation.
   *
   * Each row shows:
   *   - Vote value icon (agree / disagree / unsure)
   *   - Voter display name (members) OR a UUID identifier (Owner/Admin
   *     viewing a non-member / trusted vote) OR an anonymous placeholder
   *     when FR-039 masks the voter (`user_id === null`).
   *   - VoteSourceBadge ("Member" / "Non-member" / "Trusted")
   *   - Optional note preview
   *
   * FR-039:
   *   - Owner / Admin viewers receive `user_id` (and `user`) populated for
   *     non-member / trusted votes.  In that case we surface the UUID as a
   *     visible identifier (the spec emphasises that Owner/Admin must be
   *     able to *see* the user id) — short prefix in the row, full UUID
   *     in `aria-label` / `title` / `data-voter-uuid` for E2E inspection.
   *   - Non-Owner viewers receive `user_id === null` and the row falls
   *     back to a greyed-out anonymous label.  The vote itself, source
   *     badge, and project_role_at_vote remain visible (FR-040).
   *
   * Member votes are never masked — the row shows display_name (or email
   * fallback) directly, no UUID column.
   */
  import * as m from '$lib/paraglide/messages';
  import type { DetectionVote, VoteValue } from '$lib/types/detection';
  import VoteSourceBadge from './VoteSourceBadge.svelte';

  interface Props {
    voters: DetectionVote[];
    /** Current viewer user id, used to highlight the viewer's own vote. */
    viewerUserId?: string | null;
  }

  let { voters, viewerUserId = null }: Props = $props();

  function voteIcon(vote: VoteValue): string {
    switch (vote) {
      case 'agree':
        return '✓'; // check mark
      case 'disagree':
        return '✗'; // ballot x
      case 'unsure':
        return '?';
    }
  }

  function voteToneClass(vote: VoteValue): string {
    switch (vote) {
      case 'agree':
        return 'bg-success-light text-success';
      case 'disagree':
        return 'bg-danger-light text-danger';
      case 'unsure':
        return 'bg-stone-100 text-stone-500';
    }
  }

  /**
   * Short representation of a UUID:  `{first8}…{last4}`.
   * The full UUID is preserved in `title`, `aria-label`, and a data attribute
   * so accessibility tools and E2E tests can recover it.
   */
  function shortenUuid(uuid: string): string {
    if (uuid.length < 12) return uuid;
    return `${uuid.slice(0, 8)}…${uuid.slice(-4)}`;
  }
</script>

{#if voters.length === 0}
  <p class="text-xs text-stone-400" data-testid="voter-list-empty">
    {m.voter_list_empty()}
  </p>
{:else}
  <ul
    class="flex flex-col gap-1.5"
    data-testid="voter-list"
    aria-label={m.voter_list_label()}
  >
    {#each voters as voter (voter.id)}
      {@const isMasked = voter.user_id === null}
      {@const isSelf =
        viewerUserId !== null && voter.user_id !== null && voter.user_id === viewerUserId}
      <li
        class="flex items-center gap-2 rounded border border-stone-100 bg-white px-2 py-1.5 text-xs"
        data-testid="voter-row"
        data-vote-source={voter.source}
        data-masked={isMasked ? 'true' : 'false'}
        data-self={isSelf ? 'true' : 'false'}
      >
        <!-- Vote value icon -->
        <span
          class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded {voteToneClass(voter.vote)}"
          aria-label={voter.vote}
          title={voter.vote}
        >
          <span aria-hidden="true">{voteIcon(voter.vote)}</span>
        </span>

        <!-- Voter name (or anonymous placeholder under FR-039 masking) -->
        {#if isMasked}
          <span
            class="truncate text-stone-400 italic"
            data-testid="voter-anonymous"
          >
            {m.vote_user_anonymous()}
          </span>
        {:else if voter.source === 'member'}
          <!-- Member voters: display_name / email — no UUID exposed -->
          {#if voter.user}
            <span class="truncate text-stone-700" data-testid="voter-name">
              {voter.user.display_name ?? voter.user.email}
            </span>
          {:else}
            <span class="truncate text-stone-400 italic">
              {m.vote_user_anonymous()}
            </span>
          {/if}
        {:else if voter.user_id}
          <!--
            Non-member / Trusted voter, viewed by Owner/Admin (FR-039 unmask
            path). Surface the UUID identifier explicitly:
              - display_name (when present) plus a small UUID column, OR
              - shortened UUID alone when no display_name is available.
            The full UUID lives in `data-voter-uuid` / `title` / `aria-label`
            so E2E tests can read it back.
          -->
          {#if voter.user?.display_name || voter.user?.email}
            <span class="truncate text-stone-700" data-testid="voter-name">
              {voter.user.display_name ?? voter.user.email}
            </span>
            <span
              class="font-mono text-[10px] text-stone-400"
              data-testid="voter-uuid"
              data-voter-uuid={voter.user_id}
              title={voter.user_id}
              aria-label={m.voter_uuid_aria({ uuid: voter.user_id })}
            >
              {shortenUuid(voter.user_id)}
            </span>
          {:else}
            <span
              class="truncate font-mono text-xs text-stone-500"
              data-testid="voter-uuid"
              data-voter-uuid={voter.user_id}
              title={voter.user_id}
              aria-label={m.voter_uuid_aria({ uuid: voter.user_id })}
            >
              {shortenUuid(voter.user_id)}
            </span>
          {/if}
        {:else}
          <!-- Defensive fallback: should not happen because !isMasked
               implies user_id is non-null. -->
          <span class="truncate text-stone-400 italic">
            {m.vote_user_anonymous()}
          </span>
        {/if}

        <!-- "(you)" tag for self-vote -->
        {#if isSelf}
          <span class="text-[10px] text-stone-400">{m.voter_self_marker()}</span>
        {/if}

        <!-- Source badge — always visible (FR-040 keeps the source even when masked) -->
        <VoteSourceBadge source={voter.source} compact class="ml-auto" />
      </li>
    {/each}
  </ul>
{/if}
