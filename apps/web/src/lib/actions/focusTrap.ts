/**
 * focusTrap — Svelte 5 use:directive that traps keyboard focus inside a
 * modal/dialog node and surfaces ESC as ``onClose``.
 *
 * Phase 15 Batch 5b R2 (Codex Minor 2 fix). All admin destructive
 * dialogs and the new WebAuthn step-up prompt use this action so that
 * keyboard-only operators cannot tab away from the dialog while it is
 * open.  The action mirrors the WAI-ARIA Authoring Practices "Modal
 * Dialog" pattern:
 *
 *   - On mount, focus moves to the first focusable element inside the
 *     trap (or the trap node itself when nothing is focusable yet).
 *   - Tab / Shift+Tab cycle within the trap.  Reaching the last element
 *     wraps to the first; Shift+Tab from the first wraps to the last.
 *   - ESC invokes ``onClose`` (no-op when ``onClose`` is omitted).
 *   - On unmount, focus is restored to the element that owned focus
 *     before the trap activated, when that element is still in the DOM.
 *
 * The action is intentionally tiny and dependency-free — modal markup
 * keeps its own backdrop/role attributes; this module only handles
 * keyboard wiring.
 */

export interface FocusTrapOptions {
  /** Called when the user presses ESC inside the trap. */
  onClose?: () => void;
  /**
   * When ``false`` the trap installs its keydown listener but does NOT
   * relocate focus on mount.  Useful when the host already manages
   * initial focus.  Defaults to ``true``.
   */
  initialFocus?: boolean;
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',');

function isExplicitlyHidden(el: HTMLElement): boolean {
  if (el.hidden) return true;
  // ``style.display`` is the only reliable hint in jsdom — computed
  // styles return empty strings.  Browsers honour the same rule first,
  // and the browser-side fallback (``getComputedStyle``) catches CSS
  // class-driven hides.
  if (el.style && el.style.display === 'none') return true;
  if (typeof window !== 'undefined' && typeof window.getComputedStyle === 'function') {
    try {
      const computed = window.getComputedStyle(el);
      if (computed.display === 'none' || computed.visibility === 'hidden') {
        return true;
      }
    } catch {
      /* jsdom edge case — fall through */
    }
  }
  return false;
}

function getFocusable(node: HTMLElement): HTMLElement[] {
  const candidates = node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
  const result: HTMLElement[] = [];
  candidates.forEach((el) => {
    if (el.hasAttribute('disabled')) return;
    if (el.getAttribute('aria-hidden') === 'true') return;
    if (isExplicitlyHidden(el)) return;
    result.push(el);
  });
  return result;
}

export function focusTrap(
  node: HTMLElement,
  options: FocusTrapOptions = {},
) {
  let currentOptions: FocusTrapOptions = options;
  const previouslyFocused = (typeof document !== 'undefined'
    ? (document.activeElement as HTMLElement | null)
    : null);

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      currentOptions.onClose?.();
      return;
    }
    if (event.key !== 'Tab') return;

    const focusable = getFocusable(node);
    if (focusable.length === 0) {
      event.preventDefault();
      node.focus();
      return;
    }

    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    const active = document.activeElement as HTMLElement | null;

    if (event.shiftKey) {
      if (active === first || !node.contains(active)) {
        event.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !node.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  node.addEventListener('keydown', handleKeydown);

  // Move initial focus into the trap on the next microtask so that any
  // ``autofocus`` declarations from the consumer have a chance to win
  // first.  We yield control via ``Promise.resolve().then(...)`` rather
  // than ``setTimeout`` so vitest's fake timers do not stall the trap.
  if (currentOptions.initialFocus !== false) {
    Promise.resolve().then(() => {
      const focusable = getFocusable(node);
      const target = focusable[0] ?? node;
      // Only move focus when nothing inside the trap already has it.
      if (!node.contains(document.activeElement)) {
        target.focus();
      }
    });
  }

  return {
    update(newOptions: FocusTrapOptions) {
      currentOptions = newOptions ?? {};
    },
    destroy() {
      node.removeEventListener('keydown', handleKeydown);
      // Restore focus when feasible.  We guard against the previously
      // focused element having been detached (e.g. backdrop click that
      // unmounts a transient widget).
      if (
        previouslyFocused &&
        typeof document !== 'undefined' &&
        document.contains(previouslyFocused)
      ) {
        try {
          previouslyFocused.focus();
        } catch {
          /* ignore */
        }
      }
    },
  };
}
