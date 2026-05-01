<script lang="ts">
  /**
   * VoteSourceBreakdown - Compact 3-source vote tally (FR-038).
   *
   * Renders per-source agree/disagree counts:
   *   - Member  (always shown when there is at least one source non-zero)
   *   - Non-member (Foam tint)
   *   - Trusted (Gold tint, hidden when both agree+disagree are 0)
   *
   * The component is purely presentational. It accepts the per-source
   * counts as plain numbers so it can also be reused on a page that does
   * not yet load the full VoteSummary.
   */
  import * as m from '$lib/paraglide/messages';

  interface Props {
    memberAgree: number;
    memberDisagree: number;
    guestAuthenticatedAgree: number;
    guestAuthenticatedDisagree: number;
    trustedUserAgree: number;
    trustedUserDisagree: number;
    /** Hide the row entirely when every source has zero votes. */
    hideWhenEmpty?: boolean;
  }

  let {
    memberAgree,
    memberDisagree,
    guestAuthenticatedAgree,
    guestAuthenticatedDisagree,
    trustedUserAgree,
    trustedUserDisagree,
    hideWhenEmpty = true,
  }: Props = $props();

  const memberTotal = $derived(memberAgree + memberDisagree);
  const guestTotal = $derived(guestAuthenticatedAgree + guestAuthenticatedDisagree);
  const trustedTotal = $derived(trustedUserAgree + trustedUserDisagree);

  const allZero = $derived(memberTotal + guestTotal + trustedTotal === 0);
</script>

{#if !(hideWhenEmpty && allZero)}
  <div
    class="flex flex-wrap items-center gap-1 text-[10px]"
    role="group"
    aria-label={m.vote_breakdown_group_label()}
    data-testid="vote-source-breakdown"
  >
    <!-- Member -->
    <span
      class="inline-flex items-center gap-0.5 rounded border border-primary/30 bg-primary/10 px-1 py-0 font-medium text-primary"
      data-vote-source="member"
      aria-label={m.vote_breakdown_member_aria({
        agree: memberAgree,
        disagree: memberDisagree,
      })}
      title={m.vote_breakdown_member_aria({
        agree: memberAgree,
        disagree: memberDisagree,
      })}
    >
      {m.vote_badge_member()}
      <span class="font-semibold">{memberAgree}</span>
      <span class="opacity-60">/{memberDisagree}</span>
    </span>

    <!-- Non-member -->
    <span
      class="inline-flex items-center gap-0.5 rounded border border-info/30 bg-info-light px-1 py-0 font-medium text-info"
      data-vote-source="guest_authenticated"
      aria-label={m.vote_breakdown_guest_authenticated_aria({
        agree: guestAuthenticatedAgree,
        disagree: guestAuthenticatedDisagree,
      })}
      title={m.vote_breakdown_guest_authenticated_aria({
        agree: guestAuthenticatedAgree,
        disagree: guestAuthenticatedDisagree,
      })}
    >
      {m.vote_badge_guest_authenticated()}
      <span class="font-semibold">{guestAuthenticatedAgree}</span>
      <span class="opacity-60">/{guestAuthenticatedDisagree}</span>
    </span>

    <!-- Trusted (collapsed when zero so projects without Trusted activity stay tidy) -->
    {#if trustedTotal > 0}
      <span
        class="inline-flex items-center gap-0.5 rounded border border-warning/30 bg-warning-light px-1 py-0 font-medium text-warning"
        data-vote-source="trusted_user"
        aria-label={m.vote_breakdown_trusted_user_aria({
          agree: trustedUserAgree,
          disagree: trustedUserDisagree,
        })}
        title={m.vote_breakdown_trusted_user_aria({
          agree: trustedUserAgree,
          disagree: trustedUserDisagree,
        })}
      >
        {m.vote_badge_trusted_user()}
        <span class="font-semibold">{trustedUserAgree}</span>
        <span class="opacity-60">/{trustedUserDisagree}</span>
      </span>
    {/if}
  </div>
{/if}
