<script lang="ts">
  /**
   * VoteSourceBadge - Per-voter badge indicating the voter's relationship
   * to the project at vote-creation time.
   *
   * Scope: FR-037 / FR-038 / FR-039 — vote-side surfacing only.
   *        FR-040 (Comment author badge) is a SEPARATE concern owned by
   *        T125 (Phase 3 US11) and is implemented inside the comment
   *        rendering path; this component MUST NOT be reused there
   *        because comments carry an independent `comment_source`
   *        provenance with its own data model.
   *
   * Visual mapping (Rosé Pine theme):
   *   - `member`              → neutral/rose tone, label "Member"
   *   - `guest_authenticated` → Foam (info) tone, label "Non-member"
   *   - `trusted_user`        → Gold (warning) tone, label "Trusted"
   *
   * Trusted is rendered for forward compatibility — Phase 6 does not
   * generate Trusted votes, but the type allows it.
   *
   * The badge always renders the source name; FR-039 masking happens at the
   * `user_id` level (handled by the backend) and does not change the badge.
   */
  import * as m from '$lib/paraglide/messages';
  import type { AnnotationVoteSource } from '$lib/types/detection';

  interface Props {
    source: AnnotationVoteSource;
    /** Render in compact form (smaller text, tighter padding). */
    compact?: boolean;
    /** Additional class names appended to the badge wrapper. */
    class?: string;
  }

  let { source, compact = false, class: extraClass = '' }: Props = $props();

  const label = $derived.by(() => {
    switch (source) {
      case 'member':
        return m.vote_badge_member();
      case 'guest_authenticated':
        return m.vote_badge_guest_authenticated();
      case 'trusted_user':
        return m.vote_badge_trusted_user();
    }
  });

  const ariaLabel = $derived.by(() => {
    switch (source) {
      case 'member':
        return m.vote_badge_member_aria();
      case 'guest_authenticated':
        return m.vote_badge_guest_authenticated_aria();
      case 'trusted_user':
        return m.vote_badge_trusted_user_aria();
    }
  });

  // Tone classes follow the project's existing Rosé Pine tokens
  // (see tailwind.config / app.css). All badges share a rounded pill shape.
  const toneClass = $derived.by(() => {
    switch (source) {
      case 'member':
        // Neutral / project-internal — use the brand rose tint
        return 'bg-primary/10 text-primary border-primary/30';
      case 'guest_authenticated':
        // Foam (info) — non-member, external participation
        return 'bg-info-light text-info border-info/30';
      case 'trusted_user':
        // Gold (warning) — elevated trust
        return 'bg-warning-light text-warning border-warning/30';
    }
  });

  const sizeClass = $derived(
    compact ? 'px-1 py-0 text-[10px]' : 'px-1.5 py-0.5 text-xs',
  );
</script>

<span
  class="inline-flex items-center rounded border font-medium {toneClass} {sizeClass} {extraClass}"
  data-vote-source={source}
  aria-label={ariaLabel}
  title={ariaLabel}
>
  {label}
</span>
