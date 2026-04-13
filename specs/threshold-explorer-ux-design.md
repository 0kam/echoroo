# Threshold Explorer UX Design Proposal

## 1. Design Philosophy

The current search workflow treats each result as an individual item to review. The Threshold Explorer reframes the task: the user's real goal is to find the **similarity cutoff** that separates true detections from false positives. This is a statistical, visual task -- not a card-by-card grind.

The design draws inspiration from binary search: show the user samples at strategic similarity levels, let them quickly judge "yes/no", and converge on the threshold in minutes rather than hours.

---

## 2. Page Layout (Wireframe Description)

The Threshold Explorer replaces the current `ResultsPanel` as the **primary view** when viewing a completed search session. The existing card-grid review is preserved as a secondary "Full Review" tab.

```
+==============================================================================+
|  [<- Back to Sessions]                                                        |
|                                                                               |
|  +-- Session Header Card ------------------------------------------------+   |
|  | Japanese Bush Warbler (Horornis diphone)          Completed  142 results|   |
|  | 2026-04-06 14:32    Search: 1,240ms    [Edit & Re-search] [Fork] [CSV] |   |
|  +-----------------------------------------------------------------------+   |
|                                                                               |
|  +-- Reference Audio (collapsed by default, expandable) -----------------+   |
|  | [>] Reference Sounds (3 sources)                                       |   |
|  +-----------------------------------------------------------------------+   |
|                                                                               |
|  +-- Tab Bar ------------------------------------------------------------+   |
|  | [* Threshold Explorer]  [ Full Review ]  [ Export ]                     |   |
|  +-----------------------------------------------------------------------+   |
|                                                                               |
|  +== THRESHOLD EXPLORER TAB =============================================+   |
|  |                                                                        |   |
|  |  +-- Distribution Chart (full width) ------------------------------+  |   |
|  |  |                                                                  |  |   |
|  |  |   Similarity Distribution                                        |  |   |
|  |  |                                                                  |  |   |
|  |  |   |||                                                            |  |   |
|  |  |   |||  ||                                                        |  |   |
|  |  |   ||| |||                                                        |  |   |
|  |  |   ||| ||| ||                                                     |  |   |
|  |  |   ||| ||| ||| ||                                                 |  |   |
|  |  |   ||| ||| ||| ||| || || || | |                                   |  |   |
|  |  |   90  85  80  75  70 65 60 55 50   (similarity %)                |  |   |
|  |  |              ^                                                   |  |   |
|  |  |              | Threshold: 72%                                    |  |   |
|  |  |              | (drag to adjust)                                  |  |   |
|  |  |                                                                  |  |   |
|  |  |   [Above: 87 results]  |  [Below: 55 results]                   |  |   |
|  |  |   (green shading)      |  (gray shading)                        |  |   |
|  |  +-------------------------------------------------------------- --+  |   |
|  |                                                                        |   |
|  |  +-- Spot-Check Strip (the key innovation) ------------------------+  |   |
|  |  |                                                                  |  |   |
|  |  |  "Samples near threshold (72%)"                                  |  |   |
|  |  |                                                                  |  |   |
|  |  |  +--------+  +--------+  +--------+  +--------+  +--------+     |  |   |
|  |  |  |spectrg |  |spectrg |  |spectrg |  |spectrg |  |spectrg |     |  |   |
|  |  |  | 74%    |  | 73%    |  | 72%    |  | 71%    |  | 70%    |     |  |   |
|  |  |  |  [>]   |  |  [>]   |  |  [>]   |  |  [>]   |  |  [>]   |     |  |   |
|  |  |  +--------+  +--------+  +--------+  +--------+  +--------+     |  |   |
|  |  |  [Looks good]           [<-- threshold -->]        [Not target]  |  |   |
|  |  |                                                                  |  |   |
|  |  +------------------------------------------------------------------+  |   |
|  |                                                                        |   |
|  |  +-- Similarity Ladder (comparative view) -------------------------+  |   |
|  |  |                                                                  |  |   |
|  |  |  "What does each similarity level look like?"                    |  |   |
|  |  |                                                                  |  |   |
|  |  |  90%+ |||||||  [spectrogram] [spectrogram] [spectrogram]   [>]   |  |   |
|  |  |  80%  |||||    [spectrogram] [spectrogram] [spectrogram]   [>]   |  |   |
|  |  |  70%  ||||     [spectrogram] [spectrogram] [spectrogram]   [>]   |  |   |
|  |  |  60%  ||       [spectrogram] [spectrogram] [spectrogram]   [>]   |  |   |
|  |  |  50%  |        [spectrogram] [spectrogram] [spectrogram]   [>]   |  |   |
|  |  |                                                                  |  |   |
|  |  +------------------------------------------------------------------+  |   |
|  |                                                                        |   |
|  |  +-- Threshold Summary & Actions ----------------------------------+  |   |
|  |  |                                                                  |  |   |
|  |  |  Current Threshold: [72]%   Results above: 87                    |  |   |
|  |  |                                                                  |  |   |
|  |  |  [Export 87 detections as CSV]                                   |  |   |
|  |  |  [Create annotations from 87 results]                           |  |   |
|  |  |  [Train custom model from these results -->]                     |  |   |
|  |  |                                                                  |  |   |
|  |  +------------------------------------------------------------------+  |   |
|  |                                                                        |   |
|  +========================================================================+   |
+===============================================================================+
```

---

## 3. Component Breakdown

### 3.1 ThresholdExplorerTab (new top-level component)

**Location:** `apps/web/src/lib/components/search/ThresholdExplorerTab.svelte`

**Props:**
- `projectId: string`
- `session: SearchSession`
- `results: Record<string, SpeciesMatchResult>`
- `selectedSpeciesKey: string`

**Responsibilities:**
- Orchestrates the four sub-components below
- Manages the shared `threshold` state (reactive, drives all child components)
- Calculates derived counts (above/below threshold)

### 3.2 SimilarityHistogram (distribution chart)

**Location:** `apps/web/src/lib/components/search/SimilarityHistogram.svelte`

**Props:**
- `matches: SimilarityResult[]` -- all results for this species
- `threshold: number` -- current threshold (0-1)
- `onThresholdChange: (value: number) => void`

**Behavior:**
- Renders a horizontal bar chart / histogram with bins of 2% width (e.g., 50-52%, 52-54%, ...)
- Bars **above** threshold are colored with `success` (Pine green)
- Bars **below** threshold are colored with `stone-300` (muted)
- A vertical **draggable threshold line** (primary color) with a handle
- The line snaps to 1% increments
- Below the chart: summary text showing "Above: N results | Below: M results"
- Implementation: SVG-based for precise positioning and drag interaction
- Width: full container width, height: 160px
- Accessibility: ARIA slider role on the threshold handle

**Visual treatment:**
- Background: `bg-surface-card` with `border-card` border, rounded-lg
- Bars: `fill-success` (above) / `fill-stone-300` (below) with hover tooltip showing exact count
- Threshold line: `stroke-primary-500` with `stroke-width: 2`
- Handle: circular, `fill-primary-500`, 12px diameter, cursor: grab
- Summary text below in `text-sm text-stone-600`

### 3.3 SpotCheckStrip (boundary sampling)

**Location:** `apps/web/src/lib/components/search/SpotCheckStrip.svelte`

**Props:**
- `projectId: string`
- `matches: SimilarityResult[]`
- `threshold: number`
- `onThresholdAdjust: (direction: 'raise' | 'lower') => void`

**Behavior:**
- Selects 5-7 results near the current threshold boundary (e.g., threshold +/- 3%)
- Shows them as compact spectrogram cards in a horizontal scroll row
- Each card shows: spectrogram image, similarity %, play button
- Below the strip: two action buttons
  - "Looks correct (raise threshold)" -- raises threshold by 2%
  - "False positives here (lower threshold)" -- lowers threshold by 2%
- Cards are sorted by similarity (descending, left to right)
- The threshold-crossing boundary is marked with a subtle vertical separator

**Card design:**
- Reuses `MiniSpectrogram` at a compact 150x80px size
- Similarity badge: top-left corner, same color system as current ResultsPanel
- Play button: top-right, identical to ReviewCard
- Border: `border-success` for cards above threshold, `border-stone-200 border-dashed` for below
- Keyboard: arrow keys navigate, Space plays audio, same as existing nav

### 3.4 SimilarityLadder (comparative view)

**Location:** `apps/web/src/lib/components/search/SimilarityLadder.svelte`

**Props:**
- `projectId: string`
- `matches: SimilarityResult[]`
- `threshold: number`

**Behavior:**
- Groups results into 10%-wide bins (90%+, 80-90%, 70-80%, etc.)
- For each bin, shows:
  - A mini bar (proportional width) showing how many results are in this bin
  - 3 random sample spectrograms (clickable to play audio)
  - A "Show more" button to expand into a scrollable row
- The row at the threshold level is highlighted with a primary-colored left border
- Rows below threshold are visually dimmed (opacity: 0.5)

**Design:**
- Each row is a `flex items-center gap-3` layout
- Label: `text-sm font-mono text-stone-600` showing "90%+" etc.
- Mini bar: 60px max width, `bg-success` or `bg-stone-300` depending on threshold
- Spectrograms: 120x60px thumbnails, rounded, with hover overlay for play
- Active row: `border-l-3 border-primary-500 bg-primary-50/30`

### 3.5 ThresholdActions (export & bridge to custom model)

**Location:** `apps/web/src/lib/components/search/ThresholdActions.svelte`

**Props:**
- `projectId: string`
- `sessionId: string`
- `threshold: number`
- `resultCount: number`
- `speciesTagId: string | null`
- `speciesName: string`

**Behavior:**
- Shows the current threshold as an editable number input
- Displays count of results that would be exported
- Three action buttons:
  1. **"Export N detections as CSV"** -- downloads CSV with only results above threshold
  2. **"Create N annotations"** -- batch-creates annotation records in the database
  3. **"Train custom model"** -- navigates to the Models page with pre-filled session data
- The custom model button shows a brief explanation: "Want more accuracy? An SVM classifier can learn the exact boundary from your labeled data."

---

## 4. User Workflow (Step by Step)

### Step 1: Land on completed search session
User clicks a completed search session from the list. The page loads with the **Threshold Explorer** tab active by default (instead of the current card grid).

### Step 2: Scan the distribution
The histogram immediately shows the shape of the similarity distribution. The user can see:
- "Most results cluster around 70-80% -- that's a good sign of real detections"
- "There's a long tail down to 40% -- those are likely false positives"
- The default threshold is set at the session's `min_similarity` parameter

### Step 3: Explore the similarity ladder
Without touching the threshold yet, the user scrolls down to the Similarity Ladder. They visually compare:
- "At 90%+, all spectrograms clearly show the target species"
- "At 70%, most still look right but some are ambiguous"
- "At 50%, these are clearly different species"
They click play on a few to confirm with audio.

### Step 4: Narrow down with spot-check
The user drags the threshold line on the histogram to roughly 70%. The Spot-Check Strip updates to show 5-7 cards right around 70%.

They play through each one:
- "72% -- yes, that's the species"
- "71% -- yes but faint"  
- "68% -- no, that's background noise"

They click "False positives here" to raise the threshold to 72%.

### Step 5: Fine-tune
They repeat step 4 one or two more times, converging on e.g., 73%. The spot-check at 73% boundary shows all true detections above and false positives below.

### Step 6: Export
At the bottom, they see "87 results above 73% threshold" and choose:
- **Quick:** Export CSV for external analysis
- **Persist:** Create annotations in the database for long-term tracking
- **Advanced:** Train a custom SVM model for higher precision

### Step 7 (optional): Bridge to custom model
If the user clicks "Train custom model", the flow:
1. Navigate to `/projects/{id}/models` with query params `?from_session={sessionId}&threshold={0.73}`
2. The Create Model dialog opens pre-filled:
   - Name: auto-generated from species + session name
   - Target tag: pre-selected from the species
   - Source sessions: this session pre-checked
   - The threshold is used to auto-label: above = positive, below = negative
3. User clicks "Create & Train" -- one click from search to model

---

## 5. Tab Structure

The session detail page gets a 3-tab layout replacing the current flat view:

| Tab | Purpose | When to use |
|-----|---------|-------------|
| **Threshold Explorer** | Statistical overview + threshold finding (DEFAULT) | Primary workflow for most users |
| **Full Review** | Card grid with individual voting (current ResultsPanel) | Spot-checking individual edge cases, providing training data |
| **Export** | Batch export configuration and history | Final step after threshold is set |

The tab bar is placed between the Reference Audio section and the results area.

---

## 6. Data Requirements from Backend

### 6.1 Existing APIs (no changes needed)
- `GET /api/v1/projects/{id}/search-sessions/{session_id}` -- returns full session with all results
- `GET /api/v1/projects/{id}/recordings/{id}/spectrogram` -- returns spectrogram image
- `POST /api/v1/projects/{id}/search-sessions/{session_id}/export` -- CSV export

### 6.2 New/Modified APIs

#### 6.2.1 Threshold-filtered export
```
POST /api/v1/projects/{id}/search-sessions/{session_id}/export
Body: { "min_similarity": 0.73, "format": "csv" }
```
Add `min_similarity` filter to the existing export endpoint so only results above the threshold are included.

#### 6.2.2 Batch annotation creation
```
POST /api/v1/projects/{id}/search-sessions/{session_id}/batch-annotate
Body: { 
  "min_similarity": 0.73,
  "tag_id": "uuid",
  "source": "similarity_search_threshold"
}
```
Creates annotation records for all results above the threshold in one API call. Returns count of created annotations.

#### 6.2.3 Distribution statistics (optional, for performance)
```
GET /api/v1/projects/{id}/search-sessions/{session_id}/distribution
Query: ?bin_width=0.02&species_key=tag_id
Response: {
  "bins": [
    { "lower": 0.90, "upper": 0.92, "count": 12 },
    { "lower": 0.88, "upper": 0.90, "count": 8 },
    ...
  ],
  "total": 142,
  "min_similarity": 0.34,
  "max_similarity": 0.97,
  "mean_similarity": 0.72,
  "median_similarity": 0.74
}
```
This is optional -- the frontend can compute bins from the full results array. But if sessions have thousands of results, a server-side computation avoids sending all result data to the client.

### 6.3 Custom Model Bridge
The existing model creation API already accepts `session_ids`. We need to add an optional `threshold` field:
```
POST /api/v1/projects/{id}/custom-models
Body: {
  "name": "...",
  "target_tag_id": "...",
  "session_ids": ["..."],
  "embedding_model": "perch",
  "threshold": 0.73  // NEW: auto-label positive/negative split
}
```

---

## 7. Connection to Custom Model Feature

The Threshold Explorer is the **natural on-ramp** to the custom model pipeline:

```
Search Session
    |
    v
Threshold Explorer (find ~73% cutoff)
    |
    +-- "Good enough?" --> Export CSV / Create annotations (DONE)
    |
    +-- "Need more accuracy?" --> Train Custom Model
            |
            v
        Create SVM Model (pre-filled from session)
            |
            v
        Auto-label: above 73% = positive, below = negative
            |
            v
        Train (30 seconds)
            |
            v
        Apply model to datasets --> Higher precision detections
```

The key UX insight: the threshold explorer produces **labeled data as a side effect**. The user's act of setting a threshold at 73% implicitly labels everything above as positive and below as negative. This labeled dataset is exactly what the SVM needs for training.

The custom model dialog should show a message like:
> "This session has 87 results above 73% and 55 below. This gives the model 87 positive and 55 negative training examples -- enough for a reliable classifier."

---

## 8. What to Keep from Current UI

### Keep as-is:
- **ReviewCard component** -- reused in Spot-Check Strip and Similarity Ladder
- **MiniSpectrogram component** -- reused everywhere
- **Keyboard navigation system** -- extended to work in spot-check strip
- **Vote/review actions** -- available in the Full Review tab
- **Species tabs** -- still needed when session has multiple species
- **Session header** -- no changes
- **Reference audio section** -- collapsed by default, still expandable

### Modify:
- **ResultsPanel** -- becomes the "Full Review" tab content (renamed but code unchanged)
- **Filter bar** -- threshold slider moves from filter bar to the histogram (more visual)
- **Export button** -- moves from session header to the Export tab with threshold filtering

### New:
- **Tab bar** between reference audio and results
- **SimilarityHistogram** with draggable threshold
- **SpotCheckStrip** for boundary verification
- **SimilarityLadder** for comparative exploration
- **ThresholdActions** for export/annotate/model-bridge

---

## 9. Responsive Behavior

### Desktop (1024px+)
- Full layout as described above
- Similarity Ladder shows 3 sample spectrograms per row
- Spot-Check Strip shows 5-7 cards in a single row

### Tablet (768-1023px)
- Similarity Ladder shows 2 sample spectrograms per row
- Spot-Check Strip shows 3-5 cards, horizontally scrollable

### Mobile (< 768px)
- Histogram: full width, height reduced to 120px
- Spot-Check Strip: 2-3 cards, horizontal scroll with snap
- Similarity Ladder: 1 spectrogram per row, rest hidden behind "Show more"
- Threshold Actions: stacked vertically

---

## 10. Accessibility

- Histogram threshold handle: `role="slider"` with `aria-valuemin`, `aria-valuemax`, `aria-valuenow`
- Keyboard: Left/Right arrows adjust threshold by 1%, Shift+arrows by 5%
- All spectrograms have alt text: "Spectrogram of {recording_name} at {start_time}-{end_time}, {similarity}% similarity"
- Color is never the sole indicator: above/below threshold uses both color AND solid/dashed borders
- Screen reader announcement when threshold changes: "{N} results above threshold"

---

## 11. Dark Mode Considerations

- Histogram bars: `success` / `stone-600` (instead of stone-300)
- Threshold line: `primary-500` (auto-flips in Ros Pine dark)
- Card borders follow existing ReviewCard dark mode behavior
- Dimmed rows in Similarity Ladder: opacity 0.4 (slightly more than light mode's 0.5 to maintain readability)

---

## 12. Animation & Transitions

- Threshold drag: histogram bars recolor instantly (no transition -- drag feels responsive)
- Spot-Check Strip: cards fade-swap when threshold changes (150ms opacity transition)
- Similarity Ladder: row highlight slides smoothly (200ms transform)
- Tab switching: standard 150ms cross-fade
- All animations respect `prefers-reduced-motion`

---

## 13. Implementation Priority

### Phase 1 (MVP -- highest impact)
1. Tab bar (Threshold Explorer / Full Review)
2. SimilarityHistogram with draggable threshold
3. SpotCheckStrip with audio playback
4. ThresholdActions with filtered CSV export

### Phase 2 (Enhanced exploration)
5. SimilarityLadder comparative view
6. Batch annotation creation API + button
7. Distribution statistics API (performance optimization)

### Phase 3 (Custom model bridge)
8. Pre-filled model creation from threshold explorer
9. Auto-labeling based on threshold
10. One-click "Train custom model" flow

---

## 14. Success Metrics

- **Time to threshold:** How long from opening a session to setting a final threshold (target: < 2 minutes for sessions with < 200 results)
- **Threshold changes:** Number of adjustments before export (fewer = better UX, target: 3-5 adjustments)
- **Custom model adoption:** Percentage of users who proceed to train a model after using threshold explorer
- **Review efficiency:** Compare time spent in Full Review tab vs. old workflow (target: 80% reduction)
