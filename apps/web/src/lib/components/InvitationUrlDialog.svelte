<script lang="ts">
  /**
   * One-shot invitation URL dialog (spec/011 US6).
   *
   * Displays a freshly-issued invitation URL exactly once. The URL is
   * served with `Cache-Control: no-store` and cannot be recovered after
   * the dialog is closed, so this component carries a prominent
   * non-recoverable warning and a Copy button (modeled on the
   * `TokenDialog` "created" view). It is purely presentational — there
   * is no token/invitation-creation form here; the URL is passed in.
   *
   * Consumed by the projects/new superuser bootstrap flow now and by the
   * future collaborators page later.
   */

  import * as m from '$lib/paraglide/messages';

  interface Props {
    open: boolean;
    url: string;
    onClose: () => void;
  }

  let { open, url, onClose }: Props = $props();

  let copied = $state(false);

  /**
   * Copy the invitation URL to the clipboard with the shared 2s "Copied"
   * feedback pattern (TokenDialog lines ~77-89).
   */
  async function copyToClipboard() {
    if (!url) return;

    try {
      await navigator.clipboard.writeText(url);
      copied = true;
      setTimeout(() => {
        copied = false;
      }, 2000);
    } catch (err) {
      console.error('Failed to copy invitation URL:', err);
    }
  }

  /**
   * Handle dialog close — reset the transient copy feedback so a
   * re-open does not flash a stale "Copied" state.
   */
  function handleClose() {
    copied = false;
    onClose();
  }
</script>

{#if open}
  <!--
    Backdrop — intentionally NOT dismissible.

    The invitation URL is shown exactly once and is unrecoverable
    (served with `Cache-Control: no-store`). In the project-create flow,
    closing this dialog triggers a deferred redirect, so a single stray
    backdrop click or Escape keypress would navigate away and lose the
    URL forever. We therefore deliberately omit backdrop-click-to-close
    and Escape-to-close handlers — the explicit "Done" button (below) is
    the sole dismissal path. The button remains focusable so the dialog
    is still keyboard-accessible.
  -->
  <div class="fixed inset-0 z-50 bg-black/50"></div>

  <!-- Dialog -->
  <div
    class="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface-card p-6 shadow-xl"
    role="dialog"
    aria-modal="true"
    aria-labelledby="invitation-url-dialog-title"
    data-testid="invitation-url-dialog"
  >
    <h2 id="invitation-url-dialog-title" class="mb-4 text-xl font-semibold text-stone-900">
      {m.invitation_url_dialog_title()}
    </h2>

    <!-- Non-recoverable warning -->
    <div class="mb-4 rounded-md bg-warning-light p-4">
      <div class="flex">
        <svg
          class="h-5 w-5 flex-shrink-0 text-warning"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fill-rule="evenodd"
            d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
            clip-rule="evenodd"
          />
        </svg>
        <div class="ml-3">
          <p class="text-sm font-medium text-warning" data-testid="invitation-url-warning">
            {m.invitation_url_dialog_warning()}
          </p>
        </div>
      </div>
    </div>

    <!-- URL display -->
    <div class="mb-4">
      <div class="flex items-center gap-2">
        <input
          id="invitation-url-value"
          type="text"
          value={url}
          readonly
          class="w-full rounded-md border border-stone-300 bg-stone-50 px-3 py-2 font-mono text-sm"
          data-testid="invitation-url-value"
        />
        <button
          type="button"
          onclick={copyToClipboard}
          class="flex-shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          data-testid="copy-invitation-url-button"
        >
          {copied ? m.invitation_url_dialog_copied() : m.invitation_url_dialog_copy()}
        </button>
      </div>
    </div>

    <!-- Close button -->
    <div class="flex justify-end">
      <button
        type="button"
        onclick={handleClose}
        class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        data-testid="invitation-url-close-button"
      >
        {m.invitation_url_dialog_close()}
      </button>
    </div>
  </div>
{/if}
