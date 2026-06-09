/**
 * nonPassiveWheel — Svelte 5 use:directive that attaches a `wheel` listener
 * with `{ passive: false }` so the handler can call `preventDefault()` to
 * suppress page scrolling.
 *
 * Why this exists: the annotation overlay (`pointer-events-auto`, above the
 * spectrogram) reproduces the dataset viewer's scroll-wheel navigation. A
 * browser may register a declarative `onwheel={...}` listener as PASSIVE for
 * scroll-jank optimisation, in which case `preventDefault()` is ignored and
 * the console logs "Unable to preventDefault inside passive event listener".
 * Registering explicitly with `passive: false` guarantees the gesture pans /
 * zooms the spectrogram instead of scrolling the page.
 *
 * The handler reference is read on every event (via a closure over the latest
 * `update` value) so the parent can pass an arrow function without re-binding.
 */
export function nonPassiveWheel(node: HTMLElement, handler: (e: WheelEvent) => void) {
  let current = handler;

  function listener(e: WheelEvent) {
    current(e);
  }

  node.addEventListener('wheel', listener, { passive: false });

  return {
    update(next: (e: WheelEvent) => void) {
      current = next;
    },
    destroy() {
      node.removeEventListener('wheel', listener);
    },
  };
}
