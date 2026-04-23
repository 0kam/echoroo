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
    <optgroup label={m.timezone_group_utc()}>
      <option value="UTC">{m.timezone_utc()}</option>
    </optgroup>
    <optgroup label={m.timezone_group_asia()}>
      <option value="Asia/Tokyo">{m.timezone_asia_tokyo()}</option>
      <option value="Asia/Shanghai">{m.timezone_asia_shanghai()}</option>
      <option value="Asia/Kolkata">{m.timezone_asia_kolkata()}</option>
      <option value="Asia/Seoul">{m.timezone_asia_seoul()}</option>
    </optgroup>
    <optgroup label={m.timezone_group_australia_pacific()}>
      <option value="Australia/Sydney">{m.timezone_australia_sydney()}</option>
      <option value="Pacific/Auckland">{m.timezone_pacific_auckland()}</option>
    </optgroup>
    <optgroup label={m.timezone_group_europe()}>
      <option value="Europe/London">{m.timezone_europe_london()}</option>
      <option value="Europe/Paris">{m.timezone_europe_paris()}</option>
      <option value="Europe/Berlin">{m.timezone_europe_berlin()}</option>
    </optgroup>
    <optgroup label={m.timezone_group_americas()}>
      <option value="America/New_York">{m.timezone_america_new_york()}</option>
      <option value="America/Chicago">{m.timezone_america_chicago()}</option>
      <option value="America/Denver">{m.timezone_america_denver()}</option>
      <option value="America/Los_Angeles">{m.timezone_america_los_angeles()}</option>
      <option value="America/Sao_Paulo">{m.timezone_america_sao_paulo()}</option>
    </optgroup>
    <optgroup label={m.timezone_group_africa()}>
      <option value="Africa/Nairobi">{m.timezone_africa_nairobi()}</option>
    </optgroup>
  </select>
  <p class="text-xs text-stone-500">{m.datetime_config_timezone_hint()}</p>
</div>
