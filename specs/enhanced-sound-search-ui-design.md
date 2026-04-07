# Enhanced Sound Search -- UI Design Proposal

## 1. Design Philosophy

The enhanced search page transforms from a single-query tool into a **multi-source species search workbench**. The mental model shifts from "upload one file and see results" to "select target species, build a reference library of sounds for each, then batch-search your entire project for matches."

The design follows Echoroo's established patterns:
- Cards with `border-card bg-surface-card shadow-sm` for content sections
- Warm stone neutrals for text and backgrounds
- Primary orange (#FF5A00) for interactive elements and emphasis
- Green for success/confirmed states, red for errors/rejected
- Full dark mode support via CSS custom properties
- Inter font family, compact information density

---

## 2. Page Layout -- Top-Level Structure

```
+------------------------------------------------------------------+
| Breadcrumb: Project > Sound Search                                |
| H1: Sound Search                                                  |
| Subtitle: Find similar sounds across your recordings using        |
|           reference audio from your files or online sources        |
+------------------------------------------------------------------+
|                                                                    |
| [A] REFERENCE SOUNDS PANEL (collapsible card)                     |
|     [A1] Species management (add/remove target species)           |
|     [A2] Per-species reference sounds (add sources under each)    |
|                                                                    |
+------------------------------------------------------------------+
|                                                                    |
| [B] SEARCH CONFIGURATION BAR                                      |
|                                                                    |
+------------------------------------------------------------------+
|                                                                    |
| [C] RESULTS PANEL (grouped by species)                            |
|                                                                    |
+------------------------------------------------------------------+
|                                                                    |
| [D] EMBEDDING STATS (unchanged from current)                      |
|                                                                    |
+------------------------------------------------------------------+
```

Max width: `max-w-5xl` (wider than current `max-w-4xl` to accommodate richer content).

---

## 3. Panel [A]: Reference Sounds -- Species-First Hierarchy

The Reference Sounds panel uses a **species-first hierarchy**: users first add target species, then add reference sounds under each species. This mirrors how bioacoustic researchers think -- "I want to find Species X" comes before "here is a recording."

### 3.1 Overall Structure

A single card containing:
1. A header row with title "Reference Sounds" and an "Add Species" button
2. A list of species cards, each containing their reference sounds
3. When "Add Species" is clicked, an inline species selector appears

```
+------------------------------------------------------------------+
| REFERENCE SOUNDS                             [+ Add Species]      |
+------------------------------------------------------------------+
|                                                                    |
| (Species selector -- shown when "Add Species" is clicked)         |
|                                                                    |
| (List of species cards with nested reference sounds)              |
|                                                                    |
| (Empty state when no species added yet)                           |
|                                                                    |
+------------------------------------------------------------------+
```

### 3.2 Species Selector (Add Species Flow)

When the user clicks "Add Species", an inline panel appears at the top of the card with a typeahead search:

```
+------------------------------------------------------------------+
| REFERENCE SOUNDS                             [+ Add Species]      |
+------------------------------------------------------------------+
|                                                                    |
| +--------------------------------------------------------------+ |
| |  Add target species:                                          | |
| |  +--------------------------------------------------------+  | |
| |  |  [search icon] Type scientific or common name...        |  | |
| |  +--------------------------------------------------------+  | |
| |                                                                | |
| |  Suggestions (dropdown):                                       | |
| |  +--------------------------------------------------------+  | |
| |  |  Turdus merula         Common Blackbird           [+]  |  | |
| |  |  Turdus philomelos     Song Thrush                [+]  |  | |
| |  |  Turdus iliacus        Redwing                    [+]  |  | |
| |  +--------------------------------------------------------+  | |
| |                                                                | |
| |  Or enter a scientific name not in this project:               | |
| |  +--------------------------------------------------------+  | |
| |  |  "Turdus viscivorus"                       [Add Custom] |  | |
| |  +--------------------------------------------------------+  | |
| |                                                                | |
| |                                              [Close]          | |
| +--------------------------------------------------------------+ |
|                                                                    |
+------------------------------------------------------------------+
```

Key details:
- The typeahead searches both scientific name and common name from the project's existing tag list
- Each suggestion carries its `tag_id` -- this is the primary identifier used throughout the search workflow
- Suggestions appear as rows with scientific name (italic), common name, and a [+] button
- If the typed text does not match any known species, a "custom entry" option appears allowing free-text scientific name input. Custom entries have no `tag_id` until the backend auto-creates a Tag during search submission.
- Species already added to the reference list are shown grayed out with a checkmark instead of [+]
- The selector uses `bg-surface-page border border-card rounded-lg p-4` styling with a subtle inner glow
- Pressing Enter on the typeahead adds the top suggestion
- The panel closes via the "Close" link or automatically after adding a species (user can re-open)

### 3.3 Species Card (After Adding a Species)

Each added species appears as a card with its own "Add Source" capability:

```
+------------------------------------------------------------------+
| REFERENCE SOUNDS                             [+ Add Species]      |
+------------------------------------------------------------------+
|                                                                    |
| +--------------------------------------------------------------+ |
| | Turdus merula                                                  | |
| | Common Blackbird                            [+ Add Source] [x] | |
| |                                                                | |
| |  (reference sound list -- see 3.6)                             | |
| |                                                                | |
| |  -- or, if no sources yet: --                                  | |
| |                                                                | |
| |  [upload icon] No reference sounds yet.                        | |
| |  Click "Add Source" to upload an audio file or                  | |
| |  add a recording from a URL.                                    | |
| +--------------------------------------------------------------+ |
|                                                                    |
| +--------------------------------------------------------------+ |
| | Parus major                                                    | |
| | Great Tit                                   [+ Add Source] [x] | |
| |                                                                | |
| |  [sono/waveform] | "Teacher call" | Upload | [x]              | |
| |  [play btn]      | 0:15 duration  | 62 KB  |                  | |
| +--------------------------------------------------------------+ |
|                                                                    |
+------------------------------------------------------------------+
```

Species card design:
- Left border accent: `border-l-[3px] border-primary-400` for visual hierarchy
- Species scientific name: `text-base font-semibold italic text-text-primary`
- Common name below: `text-sm text-text-secondary`
- Top-right actions: "Add Source" button (compact, outlined) and remove [x] button
- Remove [x] removes the species and all its reference sounds (with a brief confirm tooltip: "Remove species and N sources?")
- The card has `bg-surface-card border-card rounded-lg shadow-sm` styling
- Cards are separated by `gap-3` (12px spacing)

### 3.4 Empty State (No Species Added)

When the Reference Sounds panel has no species yet:

```
+------------------------------------------------------------------+
| REFERENCE SOUNDS                             [+ Add Species]      |
+------------------------------------------------------------------+
|                                                                    |
|  [bird icon]                                                       |
|  No target species selected                                        |
|  Click "Add Species" to choose which species you want to           |
|  search for, then add reference sounds for each.                   |
|                                                                    |
+------------------------------------------------------------------+
```

- Empty state uses `text-stone-400` with a centered layout
- The bird icon uses a feather or bird silhouette from the icon set

### 3.5 Add Source Panel -- Tab Selector

When the user clicks "Add Source" on a species card, an expansion panel opens *within that species card* with two tabs:

```
+--------------------------------------------------------------+
| Turdus merula                                                  |
| Common Blackbird                            [+ Add Source] [x] |
|                                                                |
| +----------------------------------------------------------+ |
| | [Upload File]  [From URL]                      (tab bar)  | |
| +----------------------------------------------------------+ |
| | (tab content area)                                         | |
| +----------------------------------------------------------+ |
|                                                                |
| (existing source list below)                                   |
+--------------------------------------------------------------+
```

Tab styling follows Echoroo's existing filter-pill pattern from DetectionReviewGrid:
- Active tab: `bg-stone-700 text-white rounded px-3 py-1.5 text-sm font-medium`
- Inactive tab: `border border-stone-300 bg-surface-card text-stone-600 rounded px-3 py-1.5 text-sm`

**Important:** The species is already determined by the parent card -- the Upload and From URL forms do NOT need a separate species field. This simplifies the forms significantly.

### 3.5.1 Upload File Tab

Simplified form (no species field needed -- inherited from parent card):

**Step 1: File selection**

```
+----------------------------------------------------------+
|  +------------------------------------------------------+  |
|  |  [cloud-upload icon]                                  |  |
|  |  Drag and drop an audio file here                     |  |
|  |  or browse -- WAV, FLAC, MP3, OGG (max 10 MB)        |  |
|  +------------------------------------------------------+  |
+----------------------------------------------------------+
```

**Step 2: Spectrogram clip UI (appears after file is selected)**

After the user selects a file, the drop zone collapses to a compact file info row and the spectrogram clip UI appears below it. This lets the user visually identify and select the relevant portion of the audio.

```
+----------------------------------------------------------+
|  uploaded-file.wav (12.5s, 48kHz, 1.2 MB)      [x clear] |
|                                                            |
|  +------------------------------------------------------+  |
|  | [=====SPECTROGRAM IMAGE==============================] |
|  | [    |<<<< SELECTED RANGE >>>>|                      ] |
|  | [    2.3s ================== 7.8s                    ] |
|  +------------------------------------------------------+  |
|  [> Play Selection]  2.3s -- 7.8s (5.5s selected)         |
|  +--------+  +--------+                                    |
|  | Start: |  | End:   |                                    |
|  |  2.3   |  |  7.8   |  [Use Full Audio]                  |
|  +--------+  +--------+                                    |
|                                                            |
|  Label (optional):                                         |
|  +------------------------------------------------------+  |
|  |  e.g. "Male song, dawn chorus"                        |  |
|  +------------------------------------------------------+  |
|                                                            |
|                                     [Cancel]  [Add Source] |
+----------------------------------------------------------+
```

Spectrogram clip UI design details:
- **Spectrogram rendering**: Generated client-side using Web Audio API + Canvas, reusing patterns from the existing RecordingDetail spectrogram component. The spectrogram fills the full width of the panel.
- **Selection region**: A highlighted overlay on the spectrogram. The selected range is rendered at full brightness; unselected regions are dimmed with a semi-transparent dark overlay (`bg-black/40`).
- **Drag handles**: Left and right edges of the selection are draggable. Handles are rendered as thin vertical bars (`w-1.5 bg-primary-500 rounded-full cursor-col-resize`) with a subtle drop shadow. On hover/drag, handles grow slightly (`w-2`) and show a grabbing cursor.
- **Touch support**: Handles have a minimum touch target of 44x44px (invisible expanded hit area). On touch devices, a haptic-style visual pulse confirms the grab.
- **Playback**: The "Play Selection" button plays only the selected range using Web Audio API's `start(0, startTime, duration)`. Button toggles to "Stop" with a square icon when playing. A thin progress indicator sweeps across the spectrogram selection during playback.
- **Numeric inputs**: Small inline number inputs (`w-16`) for Start and End times, allowing precise adjustment in seconds with one decimal place. Values are clamped to valid ranges (Start >= 0, End <= duration, Start < End). Inputs update the spectrogram selection in real time.
- **"Use Full Audio" button**: Resets selection to the entire clip (0 to duration). Styled as a text link button: `text-sm text-primary-600 hover:underline`.
- **File info row**: Shows filename, duration, sample rate, and file size. The [x clear] button removes the file and returns to the drop zone state.
- **Default selection**: When a file is first loaded, the full audio is selected by default. The user only needs to adjust if they want to clip.

Key details:
- File size limit is smaller than the full upload feature (10 MB reference clips, not 1 GB recordings)
- The label field helps distinguish multiple recordings of the same species (e.g., "song", "call", "alarm")
- Species is inherited from the parent card -- no species typeahead needed here
- The selected time range (`start_time`, `end_time`) is included in the source data sent to the backend
- Minimum clip duration is **model-dependent**: 5s when Perch is selected, 3s when BirdNET is selected. The UI reads the current model from the Search Configuration bar and adjusts dynamically.
- A visual guide is shown above the spectrogram: "Recommended: >=5s for Perch, >=3s for BirdNET"
- Clips shorter than the model window are accepted but will be zero-padded before inference. When the selected range is shorter than the model window, a warning is displayed: "Short clip -- will be padded to [N]s"
- The handles enforce the model-dependent minimum (cannot be dragged closer than 5s for Perch or 3s for BirdNET)

### 3.5.2 From URL Tab

A simple URL input form. The user finds a recording on Xeno-canto (or another supported source in the future) in their browser, copies the URL, and pastes it here. The backend handles URL validation, metadata fetching, and audio download.

**Step 1: URL input**

```
+----------------------------------------------------------+
|  Paste a recording URL:                                    |
|  +------------------------------------------------------+  |
|  |  [link icon] e.g. https://xeno-canto.org/12345       |  |
|  +------------------------------------------------------+  |
|  Supported: Xeno-canto URLs                                |
+----------------------------------------------------------+
```

**Step 2: Loading state (after pasting a valid URL)**

```
+----------------------------------------------------------+
|  Paste a recording URL:                                    |
|  +------------------------------------------------------+  |
|  |  [link icon] https://xeno-canto.org/12345             |  |
|  +------------------------------------------------------+  |
|                                                            |
|  [spinner] Fetching recording metadata...                  |
+----------------------------------------------------------+
```

**Step 3: Metadata preview + spectrogram clip UI (after fetch completes)**

Once the backend validates the URL and fetches the audio, a metadata preview appears along with the spectrogram clip UI:

```
+----------------------------------------------------------+
|  Paste a recording URL:                                    |
|  +------------------------------------------------------+  |
|  |  [link icon] https://xeno-canto.org/12345      [x]   |  |
|  +------------------------------------------------------+  |
|                                                            |
|  +------------------------------------------------------+  |
|  | [checkmark] XC12345 -- Turdus merula                  |  |
|  | Quality: A  |  Type: song  |  12.5s  |  48kHz         |  |
|  | Recordist: John Doe  |  Location: United Kingdom       |  |
|  +------------------------------------------------------+  |
|                                                            |
|  +------------------------------------------------------+  |
|  | [=====SPECTROGRAM IMAGE==============================] |
|  | [    |<<<< SELECTED RANGE >>>>|                      ] |
|  | [    2.3s ================== 7.8s                    ] |
|  +------------------------------------------------------+  |
|  [> Play Selection]  2.3s -- 7.8s (5.5s selected)         |
|  +--------+  +--------+                                    |
|  | Start: |  | End:   |                                    |
|  |  2.3   |  |  7.8   |  [Use Full Audio]                  |
|  +--------+  +--------+                                    |
|                                                            |
|  Label (optional):                                         |
|  +------------------------------------------------------+  |
|  |  e.g. "Dawn chorus, high quality"                     |  |
|  +------------------------------------------------------+  |
|                                                            |
|                                     [Cancel]  [Add Source] |
+----------------------------------------------------------+
```

**Error state (invalid or unsupported URL)**

```
+----------------------------------------------------------+
|  Paste a recording URL:                                    |
|  +------------------------------------------------------+  |
|  |  [link icon] https://example.com/not-valid             |  |
|  +------------------------------------------------------+  |
|  [!] Unsupported URL. Please paste a Xeno-canto URL       |
|  (e.g. https://xeno-canto.org/12345)                       |
+----------------------------------------------------------+
```

Key details:
- The tab is named **"From URL"** (not "Xeno-canto") to be extensible to other audio sources in the future (e.g., Macaulay Library, iNaturalist)
- URL validation happens client-side first (pattern match for supported URL formats), then server-side for full validation
- Client-side URL patterns currently supported: `https://xeno-canto.org/{id}` and `https://www.xeno-canto.org/{id}`
- Backend extracts the XC ID from the URL, fetches metadata via XC API v3 (`https://xeno-canto.org/api/3/recordings?nr={id}`), and downloads the audio file
- The metadata preview card confirms the species, quality, type, duration, and recordist -- giving the user confidence they pasted the right URL
- The metadata preview uses `bg-green-50 border border-green-200 rounded-lg p-3` styling to indicate successful validation
- The [x] button next to the URL clears it and returns to the empty input state
- The spectrogram clip UI is identical to the one in the Upload tab (section 3.5.1) -- same component reused
- For the URL tab, the spectrogram is generated from the audio fetched by the backend. A loading state ("Fetching recording...") is shown while the backend downloads and processes the audio.
- The "Supported: Xeno-canto URLs" hint text uses `text-xs text-text-secondary`
- No API key is needed on the frontend -- all XC API interaction happens server-side
- This eliminates: XC search UI, preview player, quality/type filters, pagination, and API key concerns on the frontend
- Display XC license info (Creative Commons) in the metadata preview card so users are aware of the source license

#### URL Security Requirements
- Backend validates the URL against an **allowlist** of permitted domains (only `xeno-canto.org` for now)
- Maximum download size per URL source: **50 MB**
- Download timeout: **30 seconds**
- No redirect following to external domains (prevent SSRF)
- Downloaded audio is cached server-side with a **24-hour TTL** to avoid re-downloading the same recording
- URLs that fail validation return a clear error: "Unsupported URL domain. Only xeno-canto.org is supported."

### 3.6 Reference Sound List (Per-Species)

Within each species card, added sources appear as compact horizontal cards:

```
+--------------------------------------------------------------+
| Turdus merula                                                  |
| Common Blackbird (3 sources)              [+ Add Source] [x]  |
|                                                                |
| +----------------------------------------------------------+ |
| | [sono/waveform] | "Male song, dawn"  | Upload  | [x]      | |
| |   [play btn]    | 0:12 (full)        | 48.2 KB |           | |
| +----------------------------------------------------------+ |
| | [sono/waveform] | XC12345 - song     | URL     | [x]      | |
| |   [play btn]    | 2.3s-7.8s (5.5s)   | Qual. A |           | |
| +----------------------------------------------------------+ |
| | [sono/waveform] | XC67890 - call     | URL     | [x]      | |
| |   [play btn]    | 0:05 (full)        | Qual. B |           | |
| +----------------------------------------------------------+ |
+--------------------------------------------------------------+
```

Key design decisions:
- Source count appears in parentheses next to the common name in the species card header
- Each source is a slim horizontal card (h-14 to h-16) with:
  - Left: tiny spectrogram/sonogram thumbnail (48x48px or 64x48px) with a play button overlay. The thumbnail shows the spectrogram of the **selected clip range**, not the full audio.
  - Center: label or XC ID, type tag (song/call), clip range and duration. If the full audio is selected, shows "0:12 (full)". If clipped, shows "2.3s-7.8s (5.5s)" to indicate the selected range.
  - Right: origin badge ("Upload" in stone, "URL" in a soft teal/blue), remove button (x icon)
- The species card has a max-height with scrollable overflow when many sources are added
- Source origin badges:
  - Upload: `bg-stone-100 text-stone-600`
  - URL: `bg-sky-50 text-sky-700 border border-sky-200`

---

## 4. Panel [B]: Search Configuration Bar

A compact horizontal bar (single card, single row on desktop):

```
+------------------------------------------------------------------+
| Model: [Perch v2.0 v]  Threshold: [====|====] 50%               |
| Max results/species: [20]  Dataset: [All Datasets v]             |
|                                                                    |
|                              [Search All Species]                  |
+------------------------------------------------------------------+
```

Key details:
- "Max results" label is "Max results per species" to clarify behavior with multi-species search
- Search button text changes to "Search All Species" when multiple species are present, or stays "Search" for a single species
- The button is disabled until **at least one species has at least one reference sound**
- A validation hint appears below the button if any species has zero sources: "Add reference sounds for all species before searching"
- On mobile, this becomes a 2-column grid then stacks to single column

---

## 5. Panel [C]: Results -- Grouped by Species

### 5.1 Species Group Header

Results are displayed in collapsible species groups:

```
+------------------------------------------------------------------+
| RESULTS                                        12 matches total   |
+==================================================================+
|                                                                    |
| v Turdus merula                                    8 matches      |
|   Common Blackbird                                                 |
|   Searched with: 3 reference sounds                                |
| +--------------------------------------------------------------+ |
| |  (result cards in a list -- see 5.2)                          | |
| +--------------------------------------------------------------+ |
|                                                                    |
| v Parus major                                      4 matches      |
|   Great Tit                                                        |
|   Searched with: 1 reference sound                                 |
| +--------------------------------------------------------------+ |
| |  (result cards in a list)                                     | |
| +--------------------------------------------------------------+ |
|                                                                    |
+------------------------------------------------------------------+
```

Species group header design:
- Chevron icon (rotates when collapsed) + scientific name in `text-base font-semibold`
- Common name below in `text-sm text-stone-500`
- Match count as a pill badge on the right: `bg-primary-100 text-primary-800`
- "Searched with: N reference sounds" in `text-xs text-stone-400`
- Clicking the header collapses/expands the group
- A thin left border accent (`border-l-[3px] border-primary-400`) on the species group to create visual hierarchy

### 5.2 Individual Result Card

Each result is an enhanced version of the current list item, now richer:

```
+--------------------------------------------------------------+
| [play btn] | recording-2024-06-15_0530.wav      | 92.3%      |
|            | Dataset: Morning Survey              |  [green]   |
|            | 01:23 - 01:28  (5.0s)              |            |
|            |                        [View Recording] [Add to  |
|            |                                       Annotation]|
+--------------------------------------------------------------+
```

Changes from current design:
- Similarity badge uses the same color-coding: >= 90% green, >= 70% primary/orange, >= 50% yellow, < 50% stone
- New "Add to Annotation" link/button: creates an annotation for the matched segment, linking it to the species tag. This is a key workflow for researchers who want to build verified species datasets from search results.
- Time range now also shows duration in parentheses
- On hover, a subtle spectrogram preview could appear (stretch goal, not MVP)

### 5.3 Empty and Loading States

**Loading state**: A single loading indicator for the entire batch search. The results panel shows a skeleton with species group headers (known from the request) and 3 placeholder rows each, with a pulsing animation. All groups appear simultaneously since results arrive in a single response.

```
+------------------------------------------------------------------+
| RESULTS                                     Searching...          |
+==================================================================+
|                                                                    |
|   Turdus merula                                                    |
|   +--[skeleton row 1]--+--[skeleton]--+--[skeleton]--+            |
|   +--[skeleton row 2]--+--[skeleton]--+--[skeleton]--+            |
|   +--[skeleton row 3]--+--[skeleton]--+--[skeleton]--+            |
|                                                                    |
|   Parus major                                                      |
|   +--[skeleton row 1]--+--[skeleton]--+--[skeleton]--+            |
|   +--[skeleton row 2]--+--[skeleton]--+--[skeleton]--+            |
|   +--[skeleton row 3]--+--[skeleton]--+--[skeleton]--+            |
|                                                                    |
+------------------------------------------------------------------+
```

**No results for a species**:
```
+--------------------------------------------------------------+
|  No matches found for Turdus merula                           |
|  Try lowering the similarity threshold or adding more          |
|  reference sounds.                                             |
+--------------------------------------------------------------+
```

**No results at all**:
```
+--------------------------------------------------------------+
|  [music-note icon]                                             |
|  No similar sounds found                                       |
|  Try lowering the similarity threshold, using a different      |
|  model, or adding higher-quality reference recordings.         |
+--------------------------------------------------------------+
```

---

## 6. Interaction Flow

### Step-by-step user journey:

```
1. User navigates to /projects/[id]/search
   -> Sees "Reference Sounds" panel with empty state message
   -> "Add Species" button prominent in the card header
   -> Search config bar visible but button disabled
   -> Embedding stats visible at bottom

2. User clicks "Add Species"
   -> Inline species selector appears at the top of the panel
   -> Typeahead input is auto-focused
   -> User types "Turd" -- suggestions appear:
      "Turdus merula (Common Blackbird)"
      "Turdus philomelos (Song Thrush)"
   -> User clicks [+] on "Turdus merula"
   -> Species card appears in the panel with empty source state
   -> Species selector stays open for adding more species

3. User clicks "Close" on species selector, or adds another species

4. User clicks "Add Source" on the Turdus merula species card
   -> Expansion panel opens within the species card
   -> Two tabs: [Upload File] | [From URL]
   -> Upload tab is selected by default

5a. PATH: Upload
   -> User drags/drops or browses for an audio file
   -> Drop zone collapses; file info row + spectrogram clip UI appears
   -> Spectrogram shows the full audio waveform with entire range selected
   -> User drags left/right handles to select the relevant portion (e.g., 2.3s - 7.8s)
   -> User clicks "Play Selection" to verify the clip sounds correct
   -> Optionally types label: "Male song, dawn chorus"
   -> Clicks "Add Source"
   -> Source card appears in the species card's source list (showing clip range)
   -> Add Source panel closes (user can re-open to add more)

5b. PATH: From URL
   -> User opens Xeno-canto in their browser, searches for a recording
   -> User copies the URL (e.g., https://xeno-canto.org/12345)
   -> User pastes the URL into the input field
   -> Loading state: "Fetching recording metadata..."
   -> Backend validates URL, fetches metadata and audio via XC API v3
   -> Metadata preview appears: species confirmation, quality, type, duration
   -> Spectrogram clip UI appears below metadata (same component as Upload tab)
   -> User adjusts clip range if needed, plays selection to verify
   -> Optionally types label
   -> Clicks "Add Source"
   -> Source card appears in the species card's source list
   -> Add Source panel closes (user can re-open to add more)

6. User adds more species (repeats steps 2-5 for additional species)
   -> E.g., adds "Parus major" and uploads one reference sound

7. User adjusts search configuration
   -> Selects model (Perch recommended for similarity search)
   -> Adjusts threshold slider
   -> Sets max results per species
   -> Optionally filters to specific dataset

8. User clicks "Search All Species"
   -> Button shows spinner + "Searching..."
   -> A SINGLE API call is sent with all species and their sources
   -> Results arrive in one response, grouped by species
   -> All species groups appear simultaneously
   -> Each group shows match count

9. User reviews results
   -> Expands/collapses species groups
   -> Plays audio from results to verify
   -> Clicks "View Recording" to navigate to full recording context
   -> Clicks "Add to Annotation" to create an annotation for confirmed matches
```

### Keyboard Shortcuts (for power users)

Carry over the concept from DetectionReviewGrid:
- `Space`: Play/stop audio of focused result
- `Arrow Up/Down`: Navigate between results within a species group
- `Tab`: Move between species groups

---

## 7. Component Hierarchy

```
SearchPage (+page.svelte)
  |
  +-- PageHeader (breadcrumb, title, description)
  |
  +-- ReferenceSoundsPanel
  |     |
  |     +-- SpeciesSelector (inline typeahead, shown on "Add Species" click)
  |     |     +-- SpeciesTypeahead
  |     |     +-- SpeciesSuggestionRow (per suggestion)
  |     |
  |     +-- SpeciesCard (per added species)
  |     |     |
  |     |     +-- SpeciesCardHeader (name, common name, source count, actions)
  |     |     |
  |     |     +-- SourceCard (per reference sound)
  |     |     |     +-- AudioPreviewButton
  |     |     |     +-- OriginBadge
  |     |     |     +-- RemoveButton
  |     |     |
  |     |     +-- AddSourcePanel (collapsible, within species card)
  |     |           +-- TabSelector (Upload | From URL)
  |     |           +-- UploadSourceForm
  |     |           |     +-- DropZone (reuse pattern)
  |     |           |     +-- SpectrogramClipEditor (appears after file selected)
  |     |           |     |     +-- SpectrogramCanvas (Web Audio API + Canvas rendering)
  |     |           |     |     +-- SelectionOverlay (draggable range handles)
  |     |           |     |     +-- PlaySelectionButton
  |     |           |     |     +-- TimeRangeInputs (start/end numeric inputs)
  |     |           |     |     +-- UseFullAudioButton
  |     |           |     +-- LabelInput
  |     |           |     (no SpeciesTypeahead -- species inherited)
  |     |           |
  |     |           +-- UrlSourceForm
  |     |                 +-- UrlInput (with placeholder hint)
  |     |                 +-- MetadataPreview (species, quality, type, duration)
  |     |                 +-- SpectrogramClipEditor (same component, appears after fetch)
  |     |                 +-- LabelInput
  |     |
  |     +-- EmptyState (shown when no species added)
  |
  +-- SearchConfigBar
  |     +-- ModelSelector
  |     +-- SimilaritySlider
  |     +-- ResultLimitInput
  |     +-- DatasetFilter
  |     +-- SearchButton
  |     +-- ValidationHint (shown when species have no sources)
  |
  +-- ResultsPanel
  |     +-- SpeciesResultGroup (per species)
  |     |     +-- SpeciesGroupHeader (collapsible)
  |     |     +-- ResultItem (per match)
  |     |           +-- PlayButton
  |     |           +-- RecordingInfo
  |     |           +-- SimilarityBadge
  |     |           +-- ActionLinks (View Recording, Add to Annotation)
  |     |
  |     +-- EmptyState / LoadingState
  |
  +-- EmbeddingStatsPanel (unchanged)
```

---

## 8. Responsive Behavior

### Desktop (>= 1024px)
- Full layout as described above
- Species cards with source list: horizontal cards with all metadata visible
- Spectrogram clip editor: full-width canvas with comfortable drag handles
- URL metadata preview: horizontal layout with all fields inline
- Results: full information density

### Tablet (768px - 1023px)
- Species cards: same layout but tighter spacing
- Spectrogram clip editor: full width, time inputs below the spectrogram
- Search config: 2x2 grid instead of 4-column row

### Mobile (< 768px)
- Species selector: full-width typeahead, suggestions stack vertically
- Species cards: full width, "Add Source" and [x] wrap below the species name
- Source cards: thumbnail + label on one line, metadata on second line
- Spectrogram clip editor: full width, handles enlarged for touch (minimum 44px touch target). Start/End inputs and "Use Full Audio" stack vertically below the play button.
- URL metadata preview: stacks vertically (species on top, metadata fields below)
- Search config: single column stack
- Result items: similarity badge moves below recording info instead of right-aligned
- Species group headers: full width, match count below title instead of right-aligned
- Add Source panel: tabs as full-width buttons instead of inline pills

---

## 9. UX Considerations for Bioacoustic Researchers

### 9.1 Why Species-First Hierarchy
Bioacoustic researchers think in terms of species, not individual recordings. The species-first design mirrors their workflow: "I want to find Blackbird, Thrush, and Great Tit in this dataset." Adding species as the top-level organizer makes the intent explicit and avoids the confusion of a flat list of reference sounds that happen to be tagged with different species.

### 9.2 Why Multiple Sources Matter
Bioacoustic researchers know that a single recording is rarely sufficient for species identification. Birds have repertoire variation (different songs, calls, alarm calls), individual variation, and regional dialects. By supporting multiple reference sounds per species, the search becomes significantly more robust.

### 9.3 URL-Based Source Integration
Xeno-canto is the standard reference library in the field. Rather than embedding a full XC search UI (which would duplicate functionality the XC website already provides excellently), the "From URL" approach lets researchers use XC's own search, filtering, and preview tools. Once they find the right recording, they paste the URL and Echoroo handles the rest. This is simpler to build, simpler to use, and extensible to other sources (e.g., Macaulay Library) in the future.

### 9.3.1 Spectrogram Clip Selection
Reference recordings often contain more than the target vocalization -- ambient noise, other species, or silence. The spectrogram clip UI lets researchers visually identify and select the precise segment they want to use as a reference. This improves search accuracy because the embedding is computed from a clean, focused audio segment rather than a noisy full recording. The visual spectrogram is critical: experienced researchers can identify vocalizations faster from a spectrogram than from listening alone.

### 9.4 Species Grouping in Results
Researchers typically search for multiple species in a single session (e.g., "what species are present at dawn in this dataset?"). Grouped results let them evaluate each species independently, which matches their analytical workflow.

### 9.5 Annotation Creation from Results
The "Add to Annotation" action creates a **Sound Event Annotation** (not a detection) for the matched segment, linking it to the species tag. This directly supports the core workflow: search finds candidates, the researcher verifies by listening, then confirms by creating an annotation. This closes the loop between discovery and documentation.

**Note:** "Add to Annotation" is a **Phase 2 feature**. In Phase 1, users click "View Recording" to navigate to the recording detail page and annotate manually from there.

### 9.6 Quality Indicators
The spectrogram clip editor and sonogram thumbnails in source cards serve as visual quality indicators. Experienced researchers can judge recording quality from a spectrogram faster than by listening. The clip editor doubles as a quality assessment tool -- researchers can see noise, overlapping species, or clipping at a glance and select only the clean segments. This is a deliberate design choice for this audience.

### 9.7 Search Parameter Guidance
- Default similarity threshold of 0.5 is a reasonable starting point
- Results per species (rather than total results) ensures balanced coverage
- Model selection matters: Perch excels at general similarity, BirdNET is species-optimized

---

## 10. Color and Visual Token Reference

All colors reference the existing Sunrise Field theme tokens:

| Element                  | Light Mode                          | Dark Mode (auto via CSS vars)  |
|--------------------------|-------------------------------------|-------------------------------|
| Card background          | `bg-surface-card`                   | Automatic                     |
| Card border              | `border-card`                       | Automatic                     |
| Page background          | `bg-surface-page`                   | Automatic                     |
| Primary buttons          | `bg-primary-600 text-white`         | Automatic                     |
| Active tab               | `bg-stone-700 text-white`           | Automatic                     |
| Inactive tab             | `border-stone-300 bg-surface-card`  | Automatic                     |
| Species card accent      | `border-l-[3px] border-primary-400`     | Automatic                     |
| Species selector bg      | `bg-surface-page border-card`       | Automatic                     |
| URL origin badge         | `bg-sky-50 text-sky-700`            | `bg-sky-950 text-sky-300`     |
| Upload origin badge      | `bg-stone-100 text-stone-600`       | Automatic                     |
| Metadata preview card    | `bg-green-50 border-green-200`      | `bg-green-950 border-green-800` |
| Spectrogram selection    | Full brightness (selected region)   | Same                          |
| Spectrogram dimmed area  | `bg-black/40` overlay               | `bg-black/50` overlay         |
| Selection handles        | `bg-primary-500`                    | Automatic                     |
| Quality A badge          | `bg-green-100 text-green-700`       | Automatic                     |
| Quality B badge          | `bg-primary-100 text-primary-700`   | Automatic                     |
| Quality C badge          | `bg-yellow-100 text-yellow-700`     | Automatic                     |
| Quality D/E badge        | `bg-stone-100 text-stone-600`       | Automatic                     |
| Similarity >= 90%        | `bg-green-100 text-green-800`       | Automatic                     |
| Similarity >= 70%        | `bg-primary-100 text-primary-800`   | Automatic                     |
| Similarity >= 50%        | `bg-yellow-100 text-yellow-800`     | Automatic                     |
| Remove button            | `text-stone-300 hover:text-stone-500` | Automatic                   |
| Add Species button       | `border-primary-300 text-primary-600 hover:bg-primary-50` | Automatic |

---

## 11. State Management Architecture

```
TargetSpecies {
  id: string (client-generated UUID, used for UI state only)
  tag_id: string (primary identifier -- project tag ID if species exists, or auto-created by backend during search for custom entries)
  scientific_name: string
  common_name?: string
  sources: SoundSource[]
}

SoundSource {
  id: string (client-generated UUID)
  origin: 'upload' | 'url'
  label?: string

  // Upload-specific
  file?: File

  // URL-specific
  source_url?: string            // the pasted URL (e.g., https://xeno-canto.org/12345)
  xc_id?: string                 // extracted XC ID (set by backend during validation)
  quality?: 'A' | 'B' | 'C' | 'D' | 'E'
  recording_type?: string
  recordist?: string
  location?: string

  // Clip selection (shared -- applies to both upload and URL sources)
  start_time?: number            // clip start in seconds (null = 0)
  end_time?: number              // clip end in seconds (null = full duration)

  // Shared metadata
  duration?: number              // full audio duration in seconds
  sample_rate?: number           // e.g., 48000
  audio_data?: ArrayBuffer       // decoded audio for client-side spectrogram rendering
}

SearchState {
  species: TargetSpecies[]          // top-level organizer
  config: {
    model_name: string
    min_similarity: number
    limit_per_species: number
    dataset_id?: string
  }
  results: Map<string, SimilarityResult[]>  // keyed by tag_id (not scientific_name)
  isSearching: boolean
  searchError?: string              // single error for the batch operation
}
```

### Batch Search Architecture

The search executes as a **single batch API call**, not one call per species:

1. **Frontend collects** all species and their reference sound data (files + URLs + clip ranges)
2. **Frontend sends** a single `POST /api/v1/projects/{id}/search/batch` request using `multipart/form-data` with **two types of parts**:
   - `metadata` part: a JSON string containing the species/sources structure, config, etc.
   - `source_0`, `source_1`, ... parts: audio file uploads, referenced by `file_key` in the metadata

   **Metadata JSON structure:**
   ```json
   {
     "species": [
       {
         "tag_id": "tag-uuid-1",
         "scientific_name": "Turdus merula",
         "sources": [
           { "type": "upload", "file_key": "source_0", "start_time": 2.3, "end_time": 7.8 },
           { "type": "url", "source_url": "https://xeno-canto.org/12345", "start_time": 0, "end_time": 12.5 },
           { "type": "url", "source_url": "https://xeno-canto.org/67890", "start_time": 1.0, "end_time": 6.0 }
         ]
       },
       {
         "tag_id": "tag-uuid-2",
         "scientific_name": "Parus major",
         "sources": [
           { "type": "upload", "file_key": "source_1", "start_time": null, "end_time": null }
         ]
       }
     ],
     "model_name": "perch",
     "min_similarity": 0.5,
     "limit_per_species": 20,
     "dataset_id": null
   }
   ```
   This cleanly separates structured data from binary file uploads. `start_time` and `end_time` define the clip range in seconds. `null` values mean "use full audio." For URL sources, the backend fetches and caches the audio server-side, then clips to the specified range. When `tag_id` is absent (custom species not yet in the project), the backend auto-creates a Tag and returns its ID in the response.
3. **Backend performs**:
   - For URL sources: extracts source ID from URL, fetches audio if not already cached
   - Clips all reference audio to the specified `start_time`/`end_time` ranges
   - Batch inference on all clipped reference sounds in a single model pass
   - Per-species vector similarity search with score aggregation (see Section 12)
   - Groups and deduplicates results by species before returning
4. **Response format** (keyed by `tag_id` to avoid string fragility):
   ```json
   {
     "results": {
       "tag-uuid-1": {
         "scientific_name": "Turdus merula",
         "common_name": "Common Blackbird",
         "matches": [
           {
             "embedding_id": "...",
             "recording_id": "...",
             "recording_filename": "recording-2024-06-15_0530.wav",
             "dataset_id": "...",
             "dataset_name": "Morning Survey",
             "start_time": 83.0,
             "end_time": 88.0,
             "similarity": 0.923
           }
         ]
       },
       "tag-uuid-2": {
         "scientific_name": "Parus major",
         "common_name": "Great Tit",
         "matches": [ ... ]
       }
     },
     "total_matches": 12,
     "search_duration_ms": 1450
   }
   ```
5. **Frontend renders** all results at once -- no incremental/streaming updates needed

Benefits of batch over per-species:
- Single network roundtrip reduces latency
- Backend can optimize model inference (batch GPU operations)
- Single DB query with multiple embedding vectors is more efficient than N separate queries
- Simpler error handling -- one request succeeds or fails
- UI state management is simpler (one loading state, one error state)

---

## 12. Score Aggregation Algorithm

This section describes how similarity scores are computed and aggregated when searching with multiple reference sounds per species.

### Layer 1 -- Segments Within a Single Reference Sound

Each reference clip is processed through the selected model (Perch uses a 5s window, BirdNET uses a 3s window):
- If the clip is **longer** than the model window, the model produces multiple segments/embeddings (one per window step)
- Each segment is treated as an **independent query vector** (they are NOT averaged into a single embedding)
- If the clip is **shorter** than the model window, it is **zero-padded** before inference (consistent with the existing embedding pipeline)

### Layer 2 -- Multiple Reference Sounds Per Species

When a species has multiple reference sounds (e.g., song, call, alarm), all query vectors from all sources are searched independently:
- All query vectors from all sources of the same species are collected into a single list
- Each query vector is searched independently against the embedding index
- The final similarity score for each candidate is **`max(similarity)`** across all query vectors for that species
- This ensures diverse call types each contribute independently -- a candidate that matches the "call" reference but not the "song" reference still receives the high "call" similarity score

### Layer 3 -- Result Deduplication

After collecting all results for a species, deduplication prevents the same sound event from appearing multiple times:
- If two results are from the **same recording** and their **time ranges overlap**, keep only the one with the highest similarity score
- This prevents the same vocalization from appearing multiple times when matched by different reference sounds or different segments of the same reference

### Algorithm Summary (Pseudocode)

```
for each species:
  query_vectors = []
  for each source in species.sources:
    audio = load_and_clip(source, start_time, end_time)
    if len(audio) < model.segment_duration:
      audio = zero_pad(audio, model.segment_duration)
    segments = model.infer(audio)  # produces N embeddings
    query_vectors.extend(segments)

  all_results = []
  for qv in query_vectors:
    results = pgvector_search(qv, threshold, limit)
    all_results.extend(results)

  # Deduplicate: same recording + overlapping time -> keep max score
  deduplicated = deduplicate_by_overlap(all_results)

  # Sort by similarity descending, take top limit_per_species
  species_results = sorted(deduplicated, reverse=True)[:limit_per_species]
```

---

## 13. Constraints and Limits

| Constraint | Value |
|-----------|-------|
| Max species per search | 20 |
| Max sources per species | 10 |
| Max total upload size | 1 GB |
| URL source allowlist | Xeno-canto only (for now) |
| Min clip duration | Model-dependent (Perch: 5s, BirdNET: 3s). Shorter clips are zero-padded. |
| Max single file size | 10 MB |
| Max URL download size | 50 MB |
| URL download timeout | 30 seconds |
| URL audio cache TTL | 24 hours |

---

## 14. Internationalization (i18n)

All UI text strings must use **Paraglide message keys** (not hardcoded strings). This is consistent with the existing i18n setup across the application.

- Key naming convention: `search_*` prefix (e.g., `search_add_species`, `search_reference_sounds`, `search_no_results`)
- Both `apps/web/messages/en.json` and `apps/web/messages/ja.json` must be updated simultaneously when adding new keys
- Placeholder text, validation messages, tooltips, and empty states all require message keys
- Species names (scientific and common) are NOT translated -- they are data, not UI text

---

## 15. Implementation Priority

### Phase 1 (MVP)
1. Species selector with typeahead (Add Species flow)
2. Species cards with Add Source panel (Upload tab with spectrogram clip editor)
3. SpectrogramClipEditor component (Web Audio API + Canvas, drag handles, playback)
4. Multiple sources displayed as list within species cards (showing clip ranges)
5. Batch search execution with single API call (with clip range parameters)
6. Results grouped by species

### Phase 2
7. From URL tab with URL validation, metadata preview, and spectrogram clip editor
8. Backend XC URL resolution endpoint (validate URL, fetch metadata, cache audio)
9. "Add to Annotation" action on results
10. Keyboard shortcuts

### Phase 3
11. Sonogram/waveform thumbnails on source cards (showing clipped range)
12. Spectrogram preview on result hover
13. Batch operations on results (confirm multiple annotations at once)
14. Support for additional URL sources beyond Xeno-canto (e.g., Macaulay Library)
