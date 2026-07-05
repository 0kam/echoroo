<script lang="ts">
  /**
   * Single member-invitation form (T221).
   *
   * Presentational shell: the parent owns the issue handler, the loading
   * flag and the transient one-shot URL. This component binds the email /
   * role fields and surfaces the already-member warning + issue error.
   */
  import type { MemberInvitationRole } from '$lib/types';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    email: string;
    role: MemberInvitationRole;
    isIssuing: boolean;
    issueError: string | null;
    /** True when the typed email already belongs to an active member (#4). */
    emailIsMember: boolean;
    /** Localized already-member warning, or null when not applicable. */
    alreadyMemberWarning: string | null;
    onSubmit: (e: Event) => void;
  }

  let {
    email = $bindable(),
    role = $bindable(),
    isIssuing,
    issueError,
    emailIsMember,
    alreadyMemberWarning,
    onSubmit,
  }: Props = $props();
</script>

<h2 class="mb-4 text-lg font-semibold text-stone-900">
  {m.collaborators_invite_heading()}
</h2>
<form onsubmit={onSubmit} class="space-y-4">
  <div class="flex items-end space-x-4">
    <div class="flex-1">
      <label for="invite-email" class="block text-sm font-medium text-stone-700">
        {m.collaborators_email_label()}
      </label>
      <input
        id="invite-email"
        type="email"
        required
        bind:value={email}
        disabled={isIssuing}
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100"
        placeholder={m.collaborators_email_placeholder()}
      />
    </div>

    <div class="w-48">
      <label for="invite-role" class="block text-sm font-medium text-stone-700">
        {m.collaborators_role_label()}
      </label>
      <select
        id="invite-role"
        bind:value={role}
        disabled={isIssuing}
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100"
      >
        <option value="viewer">{m.role_viewer()}</option>
        <option value="member">{m.role_member()}</option>
        <option value="admin">{m.role_admin()}</option>
      </select>
    </div>

    <button
      type="submit"
      disabled={isIssuing || emailIsMember}
      class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
    >
      {isIssuing ? m.collaborators_issuing() : m.collaborators_issue_button()}
    </button>
  </div>

  {#if emailIsMember && alreadyMemberWarning}
    <p class="text-sm text-warning" data-testid="invite-already-member-warning">
      {alreadyMemberWarning}
    </p>
  {/if}

  {#if issueError}
    <p class="text-sm text-danger">{issueError}</p>
  {/if}
</form>
