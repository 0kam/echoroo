/**
 * Keyboard-shortcut focus guards.
 *
 * Editor shortcuts (species number keys 1-9, A/X/Z mode keys, Delete, …) are
 * registered as window-level `keydown` listeners. A window listener fires no
 * matter which element holds focus, so each handler must decide whether the
 * keystroke was meant for a focused form control instead.
 *
 * The naive guard `tag === 'INPUT'` is too broad: it also suppresses shortcuts
 * while a *non-text* control such as a zoom/scale/seek/volume slider
 * (`<input type="range">`) holds focus. That caused the "first species
 * shortcut after a zoom is lost" bug — after dragging the time-scale slider the
 * slider keeps focus, so the first number key was swallowed by the guard.
 *
 * `isTextEntryTarget` narrows the guard to genuine text-entry surfaces only:
 * text-like `<input>` types, `<textarea>`, `<select>`, and any
 * `contentEditable` element. Range sliders, checkboxes, radios, buttons and the
 * like are NOT treated as text entry, so editor shortcuts keep working while
 * they hold focus (pressing a digit on those controls does nothing useful
 * anyway).
 */

/**
 * `<input>` types that accept free text / character entry and where editor
 * shortcuts must be suppressed. Everything else (range, checkbox, radio,
 * button, color, file, …) is treated as a non-text control.
 */
const TEXT_INPUT_TYPES = new Set([
  'text',
  'search',
  'email',
  'url',
  'tel',
  'password',
  'number',
  'date',
  'datetime-local',
  'month',
  'week',
  'time',
]);

/**
 * Returns `true` when the event target is a text-entry surface that should
 * suppress global editor keyboard shortcuts (so typing a species name or a note
 * never triggers a shortcut), and `false` for non-text controls such as range
 * sliders where shortcuts should still fire.
 */
export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;

  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;

  if (tag === 'INPUT') {
    // `type` defaults to "text" when omitted; a focused range/checkbox/etc.
    // is intentionally NOT a text-entry target.
    const type = (target as HTMLInputElement).type || 'text';
    return TEXT_INPUT_TYPES.has(type);
  }

  return false;
}
