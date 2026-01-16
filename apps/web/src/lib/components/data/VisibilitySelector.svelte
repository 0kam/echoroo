<script lang="ts">
  import type { DatasetVisibility } from '$lib/types/data';

  export let value: DatasetVisibility = 'private';
  export let onChange: (visibility: DatasetVisibility) => void;
  export let disabled: boolean = false;

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

<div class="visibility-selector">
  <label class="selector-label">Visibility</label>
  <div class="options-grid">
    {#each options as option}
      <button
        type="button"
        onclick={() => handleClick(option.value)}
        {disabled}
        class="option-button"
        class:selected={value === option.value}
        class:disabled
      >
        <div class="option-header">
          {#if option.icon === 'lock'}
            <svg class="option-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" stroke-width="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" stroke-width="2" />
            </svg>
          {:else if option.icon === 'globe'}
            <svg class="option-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="12" cy="12" r="10" stroke-width="2" />
              <line x1="2" y1="12" x2="22" y2="12" stroke-width="2" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" stroke-width="2" />
            </svg>
          {/if}
          <span class="option-label">{option.label}</span>
        </div>
        <p class="option-description">{option.description}</p>
      </button>
    {/each}
  </div>
</div>

<style>
  .visibility-selector {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .selector-label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
  }

  .options-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.75rem;
  }

  .option-button {
    padding: 0.875rem;
    background: white;
    border: 2px solid #e5e7eb;
    border-radius: 0.5rem;
    text-align: left;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .option-button:hover:not(.disabled) {
    border-color: #d1d5db;
    background: #fafafa;
  }

  .option-button.selected {
    border-color: #3b82f6;
    background: #eff6ff;
  }

  .option-button.disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .option-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.375rem;
  }

  .option-icon {
    width: 1.125rem;
    height: 1.125rem;
    color: #6b7280;
  }

  .option-button.selected .option-icon {
    color: #3b82f6;
  }

  .option-label {
    font-size: 0.875rem;
    font-weight: 600;
    color: #111827;
  }

  .option-button.selected .option-label {
    color: #1d4ed8;
  }

  .option-description {
    margin: 0;
    font-size: 0.75rem;
    color: #6b7280;
    line-height: 1.4;
  }

  .option-button.selected .option-description {
    color: #3b82f6;
  }
</style>
