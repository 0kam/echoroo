import { describe, expect, it } from 'vitest';
import { isTextEntryTarget } from './keyboardGuards';

/**
 * Guards for window-level editor shortcuts. The regression these protect
 * against: a focused zoom/scale slider (<input type="range">) must NOT be
 * treated as a text-entry surface, otherwise the first species shortcut after
 * a zoom is swallowed while the slider still holds focus.
 */
describe('isTextEntryTarget', () => {
  it('returns false for null / non-element targets', () => {
    expect(isTextEntryTarget(null)).toBe(false);
  });

  it('returns false for a range slider (zoom/scale/seek/volume control)', () => {
    const input = document.createElement('input');
    input.type = 'range';
    expect(isTextEntryTarget(input)).toBe(false);
  });

  it('returns false for checkbox / radio / button inputs', () => {
    for (const type of ['checkbox', 'radio', 'button', 'submit', 'color', 'file']) {
      const input = document.createElement('input');
      input.type = type;
      expect(isTextEntryTarget(input)).toBe(false);
    }
  });

  it('returns false for non-input elements (button, div, canvas, body)', () => {
    for (const tag of ['button', 'div', 'canvas', 'body']) {
      expect(isTextEntryTarget(document.createElement(tag))).toBe(false);
    }
  });

  it('returns true for text-like input types', () => {
    for (const type of ['text', 'search', 'email', 'url', 'tel', 'password', 'number']) {
      const input = document.createElement('input');
      input.type = type;
      expect(isTextEntryTarget(input)).toBe(true);
    }
  });

  it('treats an <input> with no type as text entry (defaults to text)', () => {
    const input = document.createElement('input');
    expect(isTextEntryTarget(input)).toBe(true);
  });

  it('returns true for textarea and select', () => {
    expect(isTextEntryTarget(document.createElement('textarea'))).toBe(true);
    expect(isTextEntryTarget(document.createElement('select'))).toBe(true);
  });

  it('returns true for contentEditable elements', () => {
    const div = document.createElement('div');
    div.setAttribute('contenteditable', 'true');
    Object.defineProperty(div, 'isContentEditable', { value: true });
    expect(isTextEntryTarget(div)).toBe(true);
  });
});
