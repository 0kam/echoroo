<script lang="ts">
  /**
   * Trusted-user invite form (Owner-only, T520).
   *
   * Presentational shell: the parent owns the invite mutation, the derived
   * form-validity flag and the flash state. This component binds the email,
   * per-permission toggles and duration fields.
   */
  import * as m from '$lib/paraglide/messages';
  import {
    ALL_TRUSTED_PERMISSIONS,
    permissionLabel,
    type TrustedFlash,
    type TrustedPermissionRecord,
  } from './trustedPermissions';

  interface Props {
    email: string;
    permissions: TrustedPermissionRecord;
    durationSeconds: number;
    flash: TrustedFlash;
    isPending: boolean;
    canSubmit: boolean;
    onSubmit: () => void;
  }

  let {
    email = $bindable(),
    permissions = $bindable(),
    durationSeconds = $bindable(),
    flash,
    isPending,
    canSubmit,
    onSubmit,
  }: Props = $props();
</script>

<section
  class="mb-8 rounded-lg bg-surface-card p-6 shadow"
  aria-labelledby="trusted-invite-form-title"
  data-testid="trusted-invite-form"
>
  <h2
    id="trusted-invite-form-title"
    class="mb-4 text-lg font-semibold text-stone-900"
  >
    {m.trusted_invite_form_title()}
  </h2>

  <div class="space-y-5">
    <div>
      <label
        for="trusted-invite-email"
        class="block text-sm font-medium text-stone-700"
      >
        {m.trusted_invite_email_label()}
      </label>
      <input
        id="trusted-invite-email"
        data-testid="trusted-invite-email-input"
        type="email"
        bind:value={email}
        placeholder={m.trusted_invite_email_placeholder()}
        autocomplete="email"
        class="mt-1 block w-full max-w-md rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:cursor-not-allowed disabled:bg-stone-100 disabled:opacity-60"
        disabled={isPending}
      />
    </div>

    <fieldset>
      <legend class="block text-sm font-medium text-stone-700">
        {m.trusted_invite_granted_permissions_label()}
      </legend>
      <p class="mt-0.5 text-xs text-stone-500">
        {m.trusted_invite_granted_permissions_help()}
      </p>
      <div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {#each ALL_TRUSTED_PERMISSIONS as perm (perm)}
          <label class="flex items-start gap-2 text-sm text-stone-700">
            <input
              data-testid={`trusted-invite-perm-${perm}`}
              type="checkbox"
              bind:checked={permissions[perm]}
              disabled={isPending}
              class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
            />
            <span>{permissionLabel(perm)}</span>
          </label>
        {/each}
      </div>
    </fieldset>

    <div>
      <label
        for="trusted-invite-duration"
        class="block text-sm font-medium text-stone-700"
      >
        {m.trusted_invite_duration_label()}
      </label>
      <p
        id="trusted-invite-duration-help"
        class="mt-0.5 text-xs text-stone-500"
      >
        {m.trusted_invite_duration_help()}
      </p>
      <select
        id="trusted-invite-duration"
        data-testid="trusted-invite-duration-select"
        bind:value={durationSeconds}
        disabled={isPending}
        aria-describedby="trusted-invite-duration-help"
        class="mt-1 block w-full max-w-xs rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:cursor-not-allowed disabled:bg-stone-100 disabled:opacity-60"
      >
        <option value={30 * 24 * 3600}>
          {m.trusted_invite_duration_30_days()}
        </option>
        <option value={90 * 24 * 3600}>
          {m.trusted_invite_duration_90_days()}
        </option>
        <option value={180 * 24 * 3600}>
          {m.trusted_invite_duration_180_days()}
        </option>
        <option value={365 * 24 * 3600}>
          {m.trusted_invite_duration_365_days()}
        </option>
      </select>
    </div>

    {#if flash.kind === 'success'}
      <p
        data-testid="trusted-invite-success"
        role="status"
        class="rounded-md bg-success-light px-4 py-3 text-sm text-success"
      >
        {flash.message}
      </p>
    {:else if flash.kind === 'error'}
      <p
        data-testid="trusted-invite-error"
        role="alert"
        class="rounded-md bg-danger-light px-4 py-3 text-sm text-danger"
      >
        {flash.message}
      </p>
    {/if}

    <div class="flex justify-end">
      <button
        type="button"
        data-testid="trusted-invite-submit"
        onclick={onSubmit}
        disabled={!canSubmit || isPending}
        class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {#if isPending}
          {m.trusted_invite_submitting_button()}
        {:else}
          {m.trusted_invite_submit_button()}
        {/if}
      </button>
    </div>
  </div>
</section>
