<script lang="ts">
  /**
   * Registration + session settings cards for the admin system-settings form.
   *
   * Presentational: two-way binds the registration/session form fields and
   * reads descriptions / last-updated timestamps from the loaded settings map.
   */

  import type { SystemSetting } from '$lib/api/admin';
  import * as m from '$lib/paraglide/messages';

  let {
    settings,
    registrationMode = $bindable(),
    allowRegistration = $bindable(),
    sessionTimeoutMinutes = $bindable(),
    formatDate,
  }: {
    settings: Record<string, SystemSetting>;
    registrationMode: 'open' | 'invitation';
    allowRegistration: boolean;
    sessionTimeoutMinutes: number;
    formatDate: (dateString: string) => string;
  } = $props();

  /**
   * Handle registration mode change
   */
  function handleRegistrationModeChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    registrationMode = target.value as 'open' | 'invitation';
  }

  /**
   * Handle allow registration toggle
   */
  function handleAllowRegistrationToggle() {
    allowRegistration = !allowRegistration;
  }

  /**
   * Handle session timeout change
   */
  function handleSessionTimeoutChange(event: Event) {
    const target = event.target as HTMLInputElement;
    sessionTimeoutMinutes = parseInt(target.value, 10);
  }
</script>

<!-- Registration Settings Card -->
<div class="overflow-hidden rounded-lg bg-surface-card shadow">
  <div class="border-b border-stone-200 px-6 py-4">
    <h2 class="text-lg font-medium text-stone-900">{m.admin_settings_registration_heading()}</h2>
    <p class="mt-1 text-sm text-stone-500">
      {m.admin_settings_registration_description()}
    </p>
  </div>

  <div class="space-y-6 px-6 py-5">
    <!-- Registration Mode -->
    <div>
      <label for="registration-mode" class="block text-sm font-medium text-stone-700">
        {m.admin_settings_registration_mode_label()}
      </label>
      <select
        id="registration-mode"
        value={registrationMode}
        onchange={handleRegistrationModeChange}
        class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      >
        <option value="open">{m.admin_settings_registration_mode_open()}</option>
        <option value="invitation">{m.admin_settings_registration_mode_invitation()}</option>
      </select>
      {#if settings.registration_mode?.description}
        <p class="mt-2 text-sm text-stone-500">{settings.registration_mode.description}</p>
      {/if}
      {#if settings.registration_mode?.updated_at}
        <p class="mt-1 text-xs text-stone-400">
          {m.admin_settings_last_updated({ date: formatDate(settings.registration_mode.updated_at) })}
        </p>
      {/if}
    </div>

    <!-- Allow Registration -->
    <div>
      <div class="flex items-center justify-between">
        <div class="flex-1">
          <label for="allow-registration" class="block text-sm font-medium text-stone-700">
            {m.admin_settings_allow_registration_label()}
          </label>
          <p class="text-sm text-stone-500">{m.admin_settings_allow_registration_description()}</p>
          {#if settings.allow_registration?.updated_at}
            <p class="mt-1 text-xs text-stone-400">
              {m.admin_settings_last_updated({ date: formatDate(settings.allow_registration.updated_at) })}
            </p>
          {/if}
        </div>
        <button
          type="button"
          id="allow-registration"
          onclick={handleAllowRegistrationToggle}
          class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 {allowRegistration
            ? 'bg-primary-600'
            : 'bg-stone-200'}"
          role="switch"
          aria-checked={allowRegistration}
        >
          <span class="sr-only">{m.admin_settings_allow_registration_sr()}</span>
          <span
            aria-hidden="true"
            class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-surface-card shadow ring-0 transition duration-200 ease-in-out {allowRegistration
              ? 'translate-x-5'
              : 'translate-x-0'}"
          ></span>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Session Settings Card -->
<div class="overflow-hidden rounded-lg bg-surface-card shadow">
  <div class="border-b border-stone-200 px-6 py-4">
    <h2 class="text-lg font-medium text-stone-900">{m.admin_settings_session_heading()}</h2>
    <p class="mt-1 text-sm text-stone-500">{m.admin_settings_session_description()}</p>
  </div>

  <div class="space-y-6 px-6 py-5">
    <!-- Session Timeout -->
    <div>
      <label for="session-timeout" class="block text-sm font-medium text-stone-700">
        {m.admin_settings_session_timeout_label()}
      </label>
      <input
        type="number"
        id="session-timeout"
        value={sessionTimeoutMinutes}
        oninput={handleSessionTimeoutChange}
        min="1"
        max="10080"
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      />
      <p class="mt-2 text-sm text-stone-500">
        {m.admin_settings_session_timeout_hint()}
      </p>
      {#if settings.session_timeout_minutes?.updated_at}
        <p class="mt-1 text-xs text-stone-400">
          {m.admin_settings_last_updated({ date: formatDate(settings.session_timeout_minutes.updated_at) })}
        </p>
      {/if}
    </div>
  </div>
</div>
