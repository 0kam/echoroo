<script lang="ts">
  /**
   * TimezoneSelect - Reusable timezone dropdown with common timezone options.
   */
  import * as m from '$lib/paraglide/messages';

  interface Props {
    value: string;
    id?: string;
    onchange?: (value: string) => void;
  }

  let { value = $bindable(''), id = 'timezone-select', onchange }: Props = $props();

  function handleChange(e: Event) {
    const select = e.target as HTMLSelectElement;
    value = select.value;
    onchange?.(select.value);
  }
</script>

<div class="flex flex-col gap-1.5">
  <label class="text-sm font-medium text-stone-700" for={id}>
    {m.datetime_config_timezone_label()}
  </label>
  <select
    {id}
    {value}
    onchange={handleChange}
    class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-400 focus:outline-none focus:ring-1 focus:ring-primary-400"
  >
    <option value="">{m.datetime_config_timezone_none()}</option>
    <optgroup label="UTC">
      <option value="UTC">UTC</option>
    </optgroup>
    <optgroup label="Asia">
      <option value="Asia/Tokyo">Asia/Tokyo (JST, UTC+9)</option>
      <option value="Asia/Shanghai">Asia/Shanghai (CST, UTC+8)</option>
      <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
      <option value="Asia/Seoul">Asia/Seoul (KST, UTC+9)</option>
    </optgroup>
    <optgroup label="Australia / Pacific">
      <option value="Australia/Sydney">Australia/Sydney (AEST, UTC+10)</option>
      <option value="Pacific/Auckland">Pacific/Auckland (NZST, UTC+12)</option>
    </optgroup>
    <optgroup label="Europe">
      <option value="Europe/London">Europe/London (GMT, UTC+0)</option>
      <option value="Europe/Paris">Europe/Paris (CET, UTC+1)</option>
      <option value="Europe/Berlin">Europe/Berlin (CET, UTC+1)</option>
    </optgroup>
    <optgroup label="Americas">
      <option value="America/New_York">America/New_York (EST, UTC-5)</option>
      <option value="America/Chicago">America/Chicago (CST, UTC-6)</option>
      <option value="America/Denver">America/Denver (MST, UTC-7)</option>
      <option value="America/Los_Angeles">America/Los_Angeles (PST, UTC-8)</option>
      <option value="America/Sao_Paulo">America/Sao Paulo (BRT, UTC-3)</option>
    </optgroup>
    <optgroup label="Africa">
      <option value="Africa/Nairobi">Africa/Nairobi (EAT, UTC+3)</option>
    </optgroup>
  </select>
  <p class="text-xs text-stone-500">{m.datetime_config_timezone_hint()}</p>
</div>
