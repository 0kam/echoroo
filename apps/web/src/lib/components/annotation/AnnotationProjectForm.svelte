<script lang="ts">
  import type {
    AnnotationProjectCreate,
    AnnotationProjectDetail,
    AnnotationProjectUpdate,
    AnnotationProjectVisibility,
  } from '$lib/types/annotation';

  export let projectId: string;
  export let project: AnnotationProjectDetail | null = null;
  export let onSubmit: (data: AnnotationProjectCreate | AnnotationProjectUpdate) => Promise<void>;
  export let onCancel: () => void = () => {};

  const isEdit = !!project;

  // Form fields
  let name = project?.name ?? '';
  let description = project?.description ?? '';
  let instructions = project?.instructions ?? '';
  let visibility: AnnotationProjectVisibility = project?.visibility ?? 'private';

  let isSubmitting = false;
  let error = '';

  async function handleSubmit() {
    if (!name.trim()) {
      error = 'Name is required';
      return;
    }

    error = '';
    isSubmitting = true;

    try {
      if (isEdit) {
        const updateData: AnnotationProjectUpdate = {
          name: name.trim(),
          description: description.trim() || undefined,
          instructions: instructions.trim() || undefined,
          visibility,
        };
        await onSubmit(updateData);
      } else {
        const createData: AnnotationProjectCreate = {
          name: name.trim(),
          description: description.trim() || undefined,
          instructions: instructions.trim() || undefined,
          visibility,
        };
        await onSubmit(createData);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to save annotation project';
    } finally {
      isSubmitting = false;
    }
  }

  // projectId is reserved for future use (e.g., fetching datasets/tags for the picker)
</script>

<form class="annotation-project-form" on:submit|preventDefault={handleSubmit}>
  <div class="form-row">
    <div class="form-group full-width">
      <label for="name">Name *</label>
      <input
        id="name"
        type="text"
        bind:value={name}
        placeholder="Enter annotation project name"
        maxlength="200"
        required
      />
    </div>
  </div>

  <div class="form-row">
    <div class="form-group full-width">
      <label for="description">Description</label>
      <textarea
        id="description"
        bind:value={description}
        placeholder="Describe this annotation project"
        rows="3"
      ></textarea>
    </div>
  </div>

  <div class="form-row">
    <div class="form-group full-width">
      <label for="instructions">Instructions</label>
      <textarea
        id="instructions"
        bind:value={instructions}
        placeholder="Instructions displayed to annotators during the annotation workflow"
        rows="4"
      ></textarea>
      <p class="help-text">
        These instructions will be shown to annotators when they work on tasks in this project.
      </p>
    </div>
  </div>

  <div class="form-row">
    <div class="form-group">
      <label for="visibility">Visibility</label>
      <select id="visibility" bind:value={visibility}>
        <option value="private">Private</option>
        <option value="public">Public</option>
      </select>
      <p class="help-text">
        Private projects are only visible to project members.
      </p>
    </div>
  </div>

  {#if error}
    <div class="error-message">{error}</div>
  {/if}

  <div class="form-actions">
    <button type="button" class="btn-secondary" on:click={onCancel} disabled={isSubmitting}>
      Cancel
    </button>
    <button type="submit" class="btn-primary" disabled={isSubmitting || !name.trim()}>
      {#if isSubmitting}
        Saving...
      {:else}
        {isEdit ? 'Update Annotation Project' : 'Create Annotation Project'}
      {/if}
    </button>
  </div>
</form>

<style>
  .annotation-project-form {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .form-row {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .form-group.full-width {
    grid-column: 1 / -1;
  }

  .form-group label {
    font-weight: 500;
    font-size: 0.875rem;
    color: #374151;
  }

  input[type='text'],
  select,
  textarea {
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    transition: border-color 0.15s ease;
  }

  input[type='text']:focus,
  select:focus,
  textarea:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  textarea {
    resize: vertical;
    font-family: inherit;
  }

  .help-text {
    font-size: 0.75rem;
    color: #6b7280;
    margin: 0;
  }

  .error-message {
    padding: 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
  }

  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    padding-top: 1rem;
    border-top: 1px solid #e5e7eb;
  }

  .btn-primary,
  .btn-secondary {
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-primary {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .btn-primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }
</style>
