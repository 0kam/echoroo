# UX principles

Rules learned from the maintainer's rejections and from trial feedback. Read
before designing or changing anything a user touches. When a change is sent
back for a UX reason, add the rule here with where it came from.

1. **Anything saved must be visible where it was entered.** A note that is
   stored but never rendered reads as data loss.
   *(Trial 2026-08: annotation notes, PR #268.)*
2. **If it looks selectable, a click selects it.** Never make the keyboard the
   only way to move a selection.
   *(Trial 2026-08: detection cards, PR #268.)*
3. **When restoring or re-implementing a screen, read the previous
   implementation first** — input types, labels and domain terms. Do not
   rebuild from a generic scaffold.
   *(`target_taxa` was restored as free text labelled "対象種" and sent back.)*
4. **One naming convention per locale.** Never mix kanji, katakana and English
   species names in the same list; resolve names by source priority.
   *(Trial 2026-08, PR #259.)*
5. **A page must open at the top and scroll with the wheel.** No `h-screen`
   inside a scrolling layout, no scroll position carried across navigation.
   *(Trial 2026-08: annotation editor.)*
6. **A spinner that never resolves is a bug, not a loading state.** Find the
   cause before calling the work done.
