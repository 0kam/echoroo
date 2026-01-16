<script lang="ts">
  export let pattern: string = '';
  export let format: string = '';

  let testFilename = '';
  let testResult: { success: boolean; matched: string | null; error: string | null } | null =
    null;

  function testPattern() {
    if (!testFilename.trim()) {
      testResult = { success: false, matched: null, error: 'Please enter a filename to test' };
      return;
    }

    if (!pattern.trim()) {
      testResult = { success: false, matched: null, error: 'Pattern is required' };
      return;
    }

    try {
      const regex = new RegExp(pattern);
      const match = testFilename.match(regex);

      if (!match) {
        testResult = {
          success: false,
          matched: null,
          error: 'Pattern did not match the filename',
        };
        return;
      }

      // Show what was matched
      const matchedString = match[0];
      testResult = {
        success: true,
        matched: matchedString,
        error: null,
      };
    } catch (e) {
      testResult = {
        success: false,
        matched: null,
        error: e instanceof Error ? e.message : 'Invalid regex pattern',
      };
    }
  }

  // Auto-test when inputs change
  $: if (testFilename && pattern) {
    testPattern();
  }

  // Common examples
  const examples = [
    {
      name: 'Underscore separated (YYYYMMDD_HHMMSS)',
      pattern: '(\\d{8})_(\\d{6})',
      format: '%Y%m%d_%H%M%S',
      filename: 'recording_20240115_143022.wav',
    },
    {
      name: 'Hyphen separated (YYYY-MM-DD_HH-MM-SS)',
      pattern: '(\\d{4}-\\d{2}-\\d{2}_\\d{2}-\\d{2}-\\d{2})',
      format: '%Y-%m-%d_%H-%M-%S',
      filename: 'site1_2024-01-15_14-30-22.wav',
    },
    {
      name: 'Compact format (YYYYMMDDHHMMSS)',
      pattern: '(\\d{14})',
      format: '%Y%m%d%H%M%S',
      filename: '20240115143022_recording.wav',
    },
  ];

  function useExample(example: (typeof examples)[0]) {
    pattern = example.pattern;
    format = example.format;
    testFilename = example.filename;
  }
</script>

<div class="datetime-tester">
  <div class="tester-content">
    <div class="input-group">
      <label for="test-filename">Test Filename</label>
      <input
        id="test-filename"
        type="text"
        bind:value={testFilename}
        placeholder="example_20240115_120000.wav"
        class="test-input"
      />
    </div>

    {#if testResult}
      <div class="test-result" class:success={testResult.success} class:error={!testResult.success}>
        {#if testResult.success}
          <div class="result-header">
            <span class="icon">✓</span>
            <span class="label">Pattern matched successfully</span>
          </div>
          <div class="matched-text">
            <span class="matched-label">Matched text:</span>
            <code>{testResult.matched}</code>
          </div>
          {#if format}
            <div class="format-info">
              <span class="format-label">Will be parsed using format:</span>
              <code>{format}</code>
            </div>
          {/if}
        {:else}
          <div class="result-header">
            <span class="icon">✗</span>
            <span class="label">Pattern test failed</span>
          </div>
          <div class="error-message">{testResult.error}</div>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Examples section -->
  <div class="examples">
    <h4>Common Patterns</h4>
    <div class="example-list">
      {#each examples as example}
        <button class="example-item" on:click={() => useExample(example)}>
          <div class="example-name">{example.name}</div>
          <div class="example-details">
            <div class="example-field">
              <span class="field-label">Pattern:</span>
              <code>{example.pattern}</code>
            </div>
            <div class="example-field">
              <span class="field-label">Format:</span>
              <code>{example.format}</code>
            </div>
            <div class="example-field">
              <span class="field-label">Example:</span>
              <span class="filename">{example.filename}</span>
            </div>
          </div>
        </button>
      {/each}
    </div>
  </div>

  <div class="help-text">
    <p>
      <strong>Note:</strong> The pattern is a regular expression that extracts the datetime string
      from the filename. The format specifies how to parse the extracted string using Python's strptime
      directives (e.g., %Y for year, %m for month, %d for day, %H for hour, %M for minute, %S for second).
    </p>
  </div>
</div>

<style>
  .datetime-tester {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .tester-content {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .input-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .input-group label {
    font-weight: 500;
    font-size: 0.875rem;
    color: #374151;
  }

  .test-input {
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-family: monospace;
  }

  .test-input:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .test-result {
    padding: 1rem;
    border-radius: 0.375rem;
    font-size: 0.875rem;
  }

  .test-result.success {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
  }

  .test-result.error {
    background: #fef2f2;
    border: 1px solid #fecaca;
  }

  .result-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .success .icon {
    color: #16a34a;
    font-weight: bold;
    font-size: 1.125rem;
  }

  .error .icon {
    color: #dc2626;
    font-weight: bold;
    font-size: 1.125rem;
  }

  .success .label {
    color: #065f46;
    font-weight: 500;
  }

  .error .label {
    color: #991b1b;
    font-weight: 500;
  }

  .matched-text,
  .format-info {
    margin-bottom: 0.5rem;
  }

  .matched-label,
  .format-label {
    color: #065f46;
    margin-right: 0.5rem;
  }

  .matched-text code,
  .format-info code {
    background: white;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-family: monospace;
    color: #065f46;
    font-size: 0.875rem;
  }

  .error-message {
    color: #991b1b;
  }

  .examples {
    border-top: 1px solid #e5e7eb;
    padding-top: 1.5rem;
  }

  .examples h4 {
    margin: 0 0 1rem 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
  }

  .example-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .example-item {
    padding: 0.75rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
    cursor: pointer;
    text-align: left;
    transition: all 0.15s ease;
  }

  .example-item:hover {
    background: #f3f4f6;
    border-color: #3b82f6;
  }

  .example-name {
    font-weight: 500;
    font-size: 0.875rem;
    color: #111827;
    margin-bottom: 0.5rem;
  }

  .example-details {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .example-field {
    font-size: 0.75rem;
    color: #6b7280;
  }

  .field-label {
    font-weight: 500;
    margin-right: 0.25rem;
  }

  .example-field code {
    background: white;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    font-family: monospace;
  }

  .filename {
    font-family: monospace;
  }

  .help-text {
    padding: 0.75rem;
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    color: #92400e;
  }

  .help-text p {
    margin: 0;
  }

  .help-text strong {
    font-weight: 600;
  }
</style>
