import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { focusTrap } from './focusTrap';

/**
 * Tests for the ``focusTrap`` use:directive.
 *
 * Builds DOM via ``document.createElement`` (no innerHTML) so the suite
 * conforms to the project's no-untrusted-HTML rule.  jsdom focus
 * semantics are sufficient for cycle / ESC / initial-focus coverage.
 */

function makeButton(id: string, label: string): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.id = id;
  btn.textContent = label;
  return btn;
}

describe('focusTrap action', () => {
  let host: HTMLElement;

  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
  });

  afterEach(() => {
    while (document.body.firstChild) {
      document.body.removeChild(document.body.firstChild);
    }
  });

  it('moves initial focus to the first focusable child on mount', async () => {
    const trapNode = document.createElement('div');
    const first = document.createElement('input');
    first.id = 'first';
    const second = makeButton('second', 'Second');
    trapNode.appendChild(first);
    trapNode.appendChild(second);
    host.appendChild(trapNode);

    const cleanup = focusTrap(trapNode, {});
    await Promise.resolve();
    expect(document.activeElement?.id).toBe('first');
    cleanup.destroy();
  });

  it('cycles focus from the last focusable back to the first on Tab', async () => {
    const trapNode = document.createElement('div');
    const first = makeButton('first', 'First');
    const second = makeButton('second', 'Second');
    trapNode.appendChild(first);
    trapNode.appendChild(second);
    host.appendChild(trapNode);

    const cleanup = focusTrap(trapNode, {});
    await Promise.resolve();
    second.focus();
    expect(document.activeElement?.id).toBe('second');

    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true });
    trapNode.dispatchEvent(event);
    expect(document.activeElement?.id).toBe('first');
    cleanup.destroy();
  });

  it('cycles focus from the first focusable to the last on Shift+Tab', async () => {
    const trapNode = document.createElement('div');
    const first = makeButton('first', 'First');
    const second = makeButton('second', 'Second');
    const third = makeButton('third', 'Third');
    trapNode.appendChild(first);
    trapNode.appendChild(second);
    trapNode.appendChild(third);
    host.appendChild(trapNode);

    const cleanup = focusTrap(trapNode, {});
    await Promise.resolve();
    first.focus();

    const event = new KeyboardEvent('keydown', {
      key: 'Tab',
      shiftKey: true,
      bubbles: true,
    });
    trapNode.dispatchEvent(event);
    expect(document.activeElement?.id).toBe('third');
    cleanup.destroy();
  });

  it('invokes onClose when the user presses ESC', async () => {
    const trapNode = document.createElement('div');
    const btn = makeButton('only', 'Btn');
    trapNode.appendChild(btn);
    host.appendChild(trapNode);

    const onClose = vi.fn();
    const cleanup = focusTrap(trapNode, { onClose });
    await Promise.resolve();

    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    trapNode.dispatchEvent(event);
    expect(onClose).toHaveBeenCalledTimes(1);
    cleanup.destroy();
  });

  it('does NOT move focus when initialFocus is false', async () => {
    const sentinel = document.createElement('input');
    sentinel.id = 'sentinel';
    document.body.appendChild(sentinel);
    sentinel.focus();

    const trapNode = document.createElement('div');
    const first = makeButton('first', 'First');
    trapNode.appendChild(first);
    host.appendChild(trapNode);

    const cleanup = focusTrap(trapNode, { initialFocus: false });
    await Promise.resolve();
    expect(document.activeElement?.id).toBe('sentinel');
    cleanup.destroy();
  });
});
