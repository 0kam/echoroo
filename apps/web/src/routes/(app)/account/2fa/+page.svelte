<script lang="ts">
  /**
   * Two-factor authentication management page (Phase 4 redesign).
   *
   * Management-only view for already-enrolled users. The first-login
   * enrollment flow lives at `/2fa-setup` in the (auth) route group so
   * users who have NOT yet established a session can reach it.
   *
   * FR-072: 2FA disable is admin-only; this page just shows status.
   */

  import * as m from '$lib/paraglide/messages';
</script>

<svelte:head>
  <title>{m.auth_two_factor_page_title()}</title>
</svelte:head>

<div class="mx-auto w-full max-w-2xl px-4 py-10">
  <h1 class="text-2xl font-extrabold text-stone-900">
    {m.auth_two_factor_management_title()}
  </h1>
  <div class="mt-4 rounded-md border border-success/30 bg-success/10 p-4">
    <p class="text-sm text-stone-800">
      {m.auth_two_factor_management_enabled()}
    </p>
  </div>
  <p class="mt-4 text-sm text-stone-600">
    {m.auth_two_factor_management_admin_only()}
  </p>
</div>
