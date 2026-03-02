<script lang="ts">
  import type { DatasetVisibility } from '$lib/types/data';

  interface Props {
    value?: DatasetVisibility;
    onChange: (visibility: DatasetVisibility) => void;
    disabled?: boolean;
  }

  let { value = 'private', onChange, disabled = false }: Props = $props();

  interface VisibilityOption {
    value: DatasetVisibility;
    label: string;
    description: string;
    icon: string;
  }

  const options: VisibilityOption[] = [
    {
      value: 'private',
      label: 'Private',
      description: 'Only project members can access',
      icon: 'lock',
    },
    {
      value: 'public',
      label: 'Public',
      description: 'Anyone can view this dataset',
      icon: 'globe',
    },
  ];

  function handleClick(optionValue: DatasetVisibility) {
    if (!disabled) {
      onChange(optionValue);
    }
  }
</script>

<div class="flex flex-col gap-2">
  <span class="text-sm font-medium text-gray-700">Visibility</span>
  <div class="grid grid-cols-2 gap-3">
    {#each options as option}
      <button
        type="button"
        onclick={() => handleClick(option.value)}
        {disabled}
        class="rounded-lg border-2 p-3.5 text-left transition-all
          {value === option.value
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'}
          {disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}"
      >
        <div class="mb-1.5 flex items-center gap-2">
          {#if option.icon === 'lock'}
            <svg
              class="h-4.5 w-4.5 {value === option.value ? 'text-blue-500' : 'text-gray-500'}"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" stroke-width="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" stroke-width="2" />
            </svg>
          {:else if option.icon === 'globe'}
            <svg
              class="h-4.5 w-4.5 {value === option.value ? 'text-blue-500' : 'text-gray-500'}"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
            >
              <circle cx="12" cy="12" r="10" stroke-width="2" />
              <line x1="2" y1="12" x2="22" y2="12" stroke-width="2" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" stroke-width="2" />
            </svg>
          {/if}
          <span class="text-sm font-semibold {value === option.value ? 'text-blue-700' : 'text-gray-900'}">
            {option.label}
          </span>
        </div>
        <p class="m-0 text-xs leading-snug {value === option.value ? 'text-blue-500' : 'text-gray-500'}">
          {option.description}
        </p>
      </button>
    {/each}
  </div>
</div>
