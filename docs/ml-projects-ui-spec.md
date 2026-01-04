# ML Projects UI Specification

## Overview

This document describes the UI design for the ML Projects feature in Echoroo, a bioacoustics application for species classification using audio recordings. The ML Projects feature enables users to train custom sound detection models through a workflow-oriented process.

## Design Philosophy

### Core Principles

1. **Workflow-Oriented Design**: Guide users through the ML pipeline step-by-step
2. **Consistency with Existing Patterns**: Reuse established UI components and layouts from Datasets and Annotation Projects
3. **Visual Feedback**: Clear status indicators, progress bars, and action states
4. **Keyboard-First Labeling**: Efficient labeling with keyboard shortcuts for power users
5. **Responsive Grid Layouts**: Adaptive layouts for spectrogram galleries and card grids

### Color Palette (Status Indicators)

| Status | Light Mode | Dark Mode |
|--------|------------|-----------|
| Setup | `bg-stone-200 text-stone-700` | `bg-stone-700 text-stone-300` |
| Searching | `bg-blue-100 text-blue-700` | `bg-blue-900 text-blue-300` |
| Labeling | `bg-yellow-100 text-yellow-700` | `bg-yellow-900 text-yellow-300` |
| Training | `bg-purple-100 text-purple-700` | `bg-purple-900 text-purple-300` |
| Inference | `bg-cyan-100 text-cyan-700` | `bg-cyan-900 text-cyan-300` |
| Review | `bg-orange-100 text-orange-700` | `bg-orange-900 text-orange-300` |
| Completed | `bg-emerald-100 text-emerald-700` | `bg-emerald-900 text-emerald-300` |
| Archived | `bg-stone-300 text-stone-600` | `bg-stone-600 text-stone-400` |

---

## Page Structure

### 1. ML Projects List Page (`/ml-projects`)

#### Layout
```
+--------------------------------------------------+
|                    Hero: "ML Projects"            |
+--------------------------------------------------+
| [Status Filter v] [Dataset Filter v] [Clear]  [+ New ML Project] |
+--------------------------------------------------+
| +----------------+ +----------------+ +----------------+ |
| | Project Card 1 | | Project Card 2 | | Project Card 3 | |
| | - Name         | | - Name         | | - Name         | |
| | - Description  | | - Description  | | - Description  | |
| | - Status Badge | | - Status Badge | | - Status Badge | |
| | - Dataset      | | - Dataset      | | - Dataset      | |
| | - Stats        | | - Stats        | | - Stats        | |
| +----------------+ +----------------+ +----------------+ |
+--------------------------------------------------+
| [Previous] Page 1 of N [Next]                    |
+--------------------------------------------------+
```

#### Components

**MLProjectCard**
- Displays project name with truncation
- Status badge with icon (Clock, Search, Tags, Cpu, Play, CheckCircle, Archive)
- Dataset name with Database icon
- Target tags count with Tags icon
- Statistics: reference sound count, search session count, model count
- Hover state: `border-emerald-500`

**Filters**
- Status dropdown: All, Setup, Searching, Labeling, Training, Inference, Review, Completed, Archived
- Dataset dropdown: All datasets from user's collection
- Clear filters button (visible when filters active)

**Empty State**
- Brain icon (w-12 h-12)
- "No ML projects found"
- "Create your first ML project to start training custom sound detection models."
- Primary CTA: "Create ML Project"

---

### 2. ML Project Detail Layout (`/ml-projects/[uuid]`)

#### Header Structure
```
+--------------------------------------------------+
| [Project Name]  [Status Badge]                    |
| [Overview] [Reference Sounds] [Search] [Models] [Inference] |
+--------------------------------------------------+
```

#### Tab Navigation
Uses `SectionTabs` component with `Tab` items:
- **Overview**: LayoutDashboard icon - Default view with dashboard
- **Reference Sounds**: Music icon - Manage reference audio samples
- **Search**: Search icon - Create and manage similarity searches
- **Models**: Cpu icon - Train and manage custom models
- **Inference**: Play icon - Run batch inference and review predictions

---

### 3. Overview Tab (`/ml-projects/[uuid]`)

#### Layout
```
+--------------------------------------------------+
| +------------+ +------------+ +------------+ +------------+ |
| | Ref Sounds | | Sessions   | | Models     | | Recordings | |
| | [count]    | | [count]    | | [count]    | | [count]    | |
| +------------+ +------------+ +------------+ +------------+ |
+--------------------------------------------------+
| Workflow Progress                                 |
| [Setup] --> [Search] --> [Labeling] --> [Training] --> [Inference] --> [Review] --> [Complete] |
|                                                   |
| Current: [Status] - [Description]                 |
+--------------------------------------------------+
| +------------------------+ +------------------------+ |
| | Quick Actions          | | Project Details        | |
| | [Add Reference Sounds] | | Description: ...       | |
| | [Create Search Session]| | Dataset: [link]        | |
| | [Train Model]          | | Created: [date]        | |
| | [Run Inference]        | | Target Tags: [badges]  | |
| +------------------------+ +------------------------+ |
+--------------------------------------------------+
```

#### Components

**StatCard**
- Icon in emerald background circle
- Large count value (2xl font)
- Label text
- Clickable, navigates to respective tab

**WorkflowProgress**
- Horizontal stepper with 7 steps
- Progress line: `bg-emerald-500` for completed steps
- Current step: Ring effect `ring-4 ring-emerald-500/20`
- Step circles: Completed = CheckCircle2, Current/Pending = Circle
- Description panel below with current step info

**QuickActions Card**
- Contextual buttons based on project state
- Primary variant for current recommended action
- Secondary variant for other available actions

---

### 4. Reference Sounds Tab (`/ml-projects/[uuid]/reference-sounds`)

#### Layout
```
+--------------------------------------------------+
| Reference Sounds                                  |
| Reference sounds are used to find similar audio... |
|                                        [Active Only] [From Clip] [From Xeno-Canto] |
+--------------------------------------------------+
| +-------------+ +-------------+ +-------------+ +-------------+ |
| | Spectrogram | | Spectrogram | | Spectrogram | | Spectrogram | |
| | [time range]| | [time range]| | [time range]| | [time range]| |
| | Name        | | Name        | | Name        | | Name        | |
| | Source      | | Source      | | Source      | | Source      | |
| | Tag         | | Tag         | | Tag         | | Tag         | |
| | [Activate]  | | [Activate]  | | [Activate]  | | [Activate]  | |
| +-------------+ +-------------+ +-------------+ +-------------+ |
+--------------------------------------------------+
```

#### Components

**ReferenceSoundCard**
- Spectrogram thumbnail (aspect-ratio: 3/1)
- Time range display
- Name with truncation
- Source indicator: Globe (Xeno-Canto), Database (Clip), Music (Upload)
- External link for Xeno-Canto (XC12345)
- Tag badge
- Embedding status badge
- Active/Inactive toggle button
- Delete button (danger variant)

**AddFromXenoCantoDialog**
- Xeno-Canto ID input with helper text
- Name input
- Species Tag dropdown (from tags API)
- Start/End time inputs (optional)
- Cancel/Submit buttons

**AddFromClipDialog**
- Clip ID input
- Name input
- Species Tag dropdown
- Start/End time inputs (optional)
- Cancel/Submit buttons

**Empty State**
- Music icon
- "No reference sounds"
- "Add reference sounds to start finding similar audio in your dataset"
- Two CTAs: "From Dataset Clip" (secondary), "From Xeno-Canto" (primary)

---

### 5. Search Tab (`/ml-projects/[uuid]/search`)

#### Layout
```
+--------------------------------------------------+
| Search Sessions                                   |
| Search for similar sounds in the dataset...       |
|                                    [+ New Search Session] |
+--------------------------------------------------+
| +-------------------+ +-------------------+ +-------------------+ |
| | Session Name      | | Session Name      | | Session Name      | |
| | Description       | | Description       | | Description       | |
| | [Complete Badge]  | | [Labeling Badge]  | | [Pending Badge]   | |
| | Target: key:value | | Target: key:value | | Target: key:value | |
| | N reference sounds| | N reference sounds| | N reference sounds| |
| | Progress Bar      | | Progress Bar      | | Progress Bar      | |
| | [Delete] [Continue]| [Delete] [Continue]| [Delete] [View]    | |
| +-------------------+ +-------------------+ +-------------------+ |
+--------------------------------------------------+
```

#### Components

**SessionCard**
- Session name (clickable, navigates to detail)
- Description with line-clamp-2
- Status badge: Complete (emerald), Labeling (blue), Pending (yellow)
- Target tag display
- Reference sounds count
- Labeling progress bar (when search complete)
- Delete button and navigation button

**CreateSessionDialog**
- Session name input
- Description textarea (optional)
- Target Tag dropdown
- Reference Sounds multi-select (checkboxes)
- Similarity Threshold input (0.01-1.00, default 0.7)
- Max Results input (default 1000)

---

### 6. Search Session Detail (`/ml-projects/[uuid]/search/[session_uuid]`)

#### Layout (Before Execution)
```
+--------------------------------------------------+
| [<- Back] Session Name                            |
|           Target: key:value                       |
+--------------------------------------------------+
| +--------------------------------------------------+ |
| |                Search Not Executed               | |
| |    Execute the search to find similar sounds...  | |
| |              [Execute Search]                    | |
| +--------------------------------------------------+ |
+--------------------------------------------------+
```

#### Layout (After Execution - Labeling Mode)
```
+--------------------------------------------------+
| [<- Back] Session Name                [Mark Complete] |
|           Target: key:value                       |
+--------------------------------------------------+
| Labeling Progress                                 |
| [=========================================] 45/100 |
| Positive: 20 | Negative: 15 | Uncertain: 5 | Unlabeled: 60 |
+--------------------------------------------------+
| [Filter: All v] 100 results                       |
+--------------------------------------------------+
| Results Grid (8 cols)          | Labeling Panel  |
| +----+ +----+ +----+ +----+   | Result #5       |
| |    | |    | |    | |    |   | Sim: 85.2%      |
| |85% | |72% | |68% | |65% |   | [Spectrogram]   |
| |[+] | |[-] | |[?] | |   |   | Label: [badge]  |
| +----+ +----+ +----+ +----+   | [P] [N] [U] [S] |
| +----+ +----+ +----+ +----+   | [<-]      [->]  |
| |    | |    | |    | |    |   |                 |
| |    | |    | |    | |    |   | Keyboard Help   |
| |    | |    | |    | |    |   | P - Positive    |
| +----+ +----+ +----+ +----+   | N - Negative    |
|                               | U - Uncertain   |
| [Previous] Page 1/5 [Next]    | S - Skip        |
+--------------------------------------------------+
```

#### Components

**ResultCard**
- Spectrogram thumbnail (aspect-ratio: 2/1)
- Similarity percentage badge (top-right, blue)
- Label badge (bottom-left): unlabeled, positive, negative, uncertain, skipped
- Rank number (bottom-right)
- Selected state: `ring-2 ring-emerald-500 border-emerald-500`

**LabelingPanel**
- Current result rank and similarity
- Larger spectrogram view
- Current label badge
- Label buttons: Positive(P), Negative(N), Uncertain(U), Skip(S)
- Navigation: Previous/Next arrows

**KeyboardShortcutsHelp Card**
- P - Positive
- N - Negative
- U - Uncertain
- S - Skip
- Left Arrow - Previous
- Right Arrow - Next

**Label Color Scheme**
| Label | Color |
|-------|-------|
| Unlabeled | stone-100/stone-600 |
| Positive | emerald-100/emerald-700 |
| Negative | red-100/red-700 |
| Uncertain | yellow-100/yellow-700 |
| Skipped | stone-200/stone-500 |

---

### 7. Models Tab (`/ml-projects/[uuid]/models`)

#### Layout
```
+--------------------------------------------------+
| Custom Models                                     |
| Train custom detection models using labeled data  |
|                                        [+ New Model] |
+--------------------------------------------------+
| +---------------------------+ +---------------------------+ |
| | Model Name                | | Model Name                | |
| | Description    [Trained]  | | Description     [Draft]   | |
| | Type: Logistic Regression | | Type: MLP Small           | |
| | Target: key:value         | | Target: key:value         | |
| | Train: 500 | Val: 100     | | Train: 300 | Val: 50      | |
| | +--------+ +--------+     | |                           | |
| | |Accuracy| |Precision|    | |                           | |
| | | 92.5%  | |  88.3%  |    | |                           | |
| | +--------+ +--------+     | |                           | |
| | +--------+ +--------+     | |                           | |
| | | Recall | | F1     |     | |                           | |
| | | 85.7%  | | 87.0%  |     | |                           | |
| | +--------+ +--------+     | |                           | |
| | [Delete] [Archive] [Deploy]| [Delete]   [Start Training]| |
| +---------------------------+ +---------------------------+ |
+--------------------------------------------------+
```

#### Components

**ModelCard**
- Model name with status badge
- Description with line-clamp
- Model type label (Logistic Regression, Linear SVM, MLP Small, MLP Medium, Random Forest)
- Target tag
- Training/Validation sample counts
- Metrics grid (when trained): Accuracy, Precision, Recall, F1 Score
- Error message panel (when failed): red background
- Action buttons by status:
  - Draft: "Start Training"
  - Training: Spinner animation
  - Trained: "Archive", "Deploy"
  - Deployed: "Archive"
  - Failed: "Retry Training"

**CreateModelDialog**
- Model name input
- Description textarea
- Target Tag dropdown
- Model Type dropdown with descriptions
- Training Data: Multi-select search sessions (checkboxes)

**Model Status Colors**
| Status | Color |
|--------|-------|
| Draft | stone-200/stone-700 |
| Training | blue-100/blue-700 (animated spinner) |
| Trained | emerald-100/emerald-700 |
| Failed | red-100/red-700 |
| Deployed | purple-100/purple-700 |
| Archived | stone-300/stone-600 |

---

### 8. Inference Tab (`/ml-projects/[uuid]/inference`)

#### Layout
```
+--------------------------------------------------+
| Inference                                         |
| Run trained models on new data to detect sounds   |
|                                [+ New Inference Batch] |
+--------------------------------------------------+
| +--------------------------------------------------+ |
| | Batch Name                        [Completed]     | |
| | Description                                       | |
| | Model: Bird Detector v1 | Threshold: 50%          | |
| | Progress: [===============================] 100%  | |
| | 1500/1500 items | 127 positive predictions        | |
| | [Delete]                                          | |
| |                                                   | |
| | [v] Expand to review predictions                  | |
| |                                                   | |
| | Filter: [All v] 127 predictions                   | |
| | +--------+ +--------+ +--------+ +--------+       | |
| | |  92%   | |  88%   | |  76%   | |  65%   |       | |
| | | [V] [X]| | [V] [X]| | [V] [X]| | [V] [X]|       | |
| | +--------+ +--------+ +--------+ +--------+       | |
| +--------------------------------------------------+ |
+--------------------------------------------------+
```

#### Components

**BatchCard**
- Collapsible card design (chevron toggle)
- Batch name with status badge
- Model name and confidence threshold
- Progress bar with counts
- Positive predictions count
- Actions by status:
  - Pending: "Start"
  - Running: "Cancel" (with refresh interval)
  - Completed: Expand to review
  - Failed: Error message display

**PredictionCard** (in expanded view)
- Spectrogram thumbnail
- Confidence badge (top-right)
- Predicted class indicator (Positive/Negative)
- Review status badge
- Quick review buttons: Confirm (Check), Reject (X), Uncertain (?)

**CreateBatchDialog**
- Batch name input
- Description textarea
- Model dropdown (deployed models only)
- Confidence Threshold input (0.01-1.00, default 0.5)
- Batch Size input (default 100)

**Review Status Colors**
| Status | Color |
|--------|-------|
| Unreviewed | stone-100/stone-600 |
| Confirmed | emerald-100/emerald-700 |
| Rejected | red-100/red-700 |
| Uncertain | yellow-100/yellow-700 |

---

## Reusable Components

### From `/lib/components/ui/`
| Component | Usage |
|-----------|-------|
| Button | All action buttons (primary, secondary, danger, text modes) |
| Card | Container for all cards |
| Dialog/DialogOverlay | All create/edit modals |
| Empty | Empty states |
| Loading | Loading states |
| ProgressBar | Progress indicators |
| Hero | List page headers |
| Tab | Tab navigation items |
| Link | Internal navigation |

### From `/lib/components/navigation/`
| Component | Usage |
|-----------|-------|
| SectionTabs | Project detail header with tabs |

### Icons (lucide-react)
- **Navigation**: LayoutDashboard, ChevronLeft, ChevronRight, ArrowLeft, ArrowRight
- **Status**: Clock, CheckCircle, XCircle, HelpCircle, Archive, Loader2
- **Actions**: Plus, Play, Pause, Trash2, ToggleLeft, ToggleRight
- **Content**: Music, Database, Globe, Search, Cpu, Tags, Filter
- **Metrics**: BarChart2, Target, Percent, Layers

---

## User Flows

### Flow 1: Create ML Project
1. Navigate to `/ml-projects`
2. Click "New ML Project"
3. Fill in name, description, select dataset
4. Submit -> Redirected to project overview

### Flow 2: Add Reference Sounds
1. From project overview, click "Add Reference Sounds" or navigate to Reference Sounds tab
2. Click "From Xeno-Canto" or "From Clip"
3. Fill in details (ID, name, tag, time range)
4. Submit -> Sound added to list

### Flow 3: Create and Execute Search
1. Navigate to Search tab
2. Click "New Search Session"
3. Select target tag, reference sounds, set threshold
4. Submit -> Session created
5. Click session card -> Navigate to detail
6. Click "Execute Search" -> Wait for completion
7. Label results using keyboard shortcuts (P/N/U/S)
8. Click "Mark Complete" when done

### Flow 4: Train Model
1. Navigate to Models tab
2. Click "New Model"
3. Select model type, target tag, training sessions
4. Submit -> Model created in draft state
5. Click "Start Training" -> Wait for completion
6. View metrics when trained
7. Click "Deploy" to enable for inference

### Flow 5: Run Inference
1. Navigate to Inference tab
2. Click "New Inference Batch"
3. Select deployed model, set threshold
4. Submit -> Batch created
5. Click "Start" -> Wait for completion
6. Expand batch to review predictions

---

### 9. Dataset Detail: Run Foundation Models

#### Overview
- Species Detection is now embedded on the Dataset Detail View as the **Run foundation models** section (see `back/docs/developer_guide/dataset_metadata_ui.md` for placement)
- Users run either BirdNET v2.4 or Perch v2.0 against a dataset slice; each run produces both classification summaries and embeddings in a single job
- Completed runs drive the Species summary table and feed the "Create annotation project from this result" CTA

#### Layout
```
+--------------------------------------------------+
| Dataset Header / Metadata (existing)              |
+--------------------------------------------------+
| Datetime Parse Status (existing)                  |
+--------------------------------------------------+
| Run foundation models                             |
| +-------------------+ +-------------------------+ |
| | Executed Models   | | Species Summary         | |
| | BirdNET v2.4  ✅   | | [Table rows...]         | |
| | Perch v2.0   Run→ | |                         | |
| +-------------------+ +-------------------------+ |
| [Run foundation models]  [View run history]       |
+--------------------------------------------------+
```

#### Components

**FoundationModelsSummaryCard**
- Description text explaining that running a foundation model will generate detections + embeddings with one job to save compute
- Primary button: "Run foundation models" (project manager only)
- Secondary link button: "View run history" (opens drawer)

**ExecutedModelsList**
- Renders each record from `foundation_model` (BirdNET v2.4, Perch v2.0, future entries)
- Fields per row:
  - Model name + version and provider badge
  - Status chip: `Not run`, `Queued`, `Running`, `Last run <relative time>`, `Failed`
  - Action buttons: View summary (navigates to last run detail), Download outputs, Rerun
- Status is derived from the latest `foundation_model_run` linked to that model + dataset

**SpeciesSummaryTable**
- Pulls aggregated rows from the latest completed run for the selected model
- Columns:
  - **Scientific Name**: canonical GBIF name rendered as a tag badge (associated tag ID displayed on hover)
  - **Common Name (JA)**: BirdNET-provided Japanese label (empty when BirdNET omitted it or parsing failed)
  - **Detections**: clip count
  - **Avg Confidence**: numeric with sparkline bar
- Table level controls: model selector pills (BirdNET / Perch), "Create annotation project from this result" button
- Opening the CTA launches the annotation project wizard pre-populated with the classification CSV for the selected run

**FoundationModelRunHistoryDrawer**
- Slide-over anchored from the right
- List view with sortable columns: Model, Status, Requested by, Started, Duration, Confidence threshold
- Each row exposes download links for classification CSV + embeddings store key and a "Create AP" shortcut
- When a run is `Running`, show streaming progress of main tasks (Decode audio, BirdNET inference, Embedding sync)

**RunFoundationModelDialog**
- Triggered from the summary card or from an ExecutedModelsList row
- Form fields:
  - **Model selection**: radio group (`BirdNET v2.4`, `Perch v2.0`)
  - **Confidence Threshold**: slider/input (0.01–0.99, default 0.10 for both models)
  - **Dataset scope**: Entire dataset (default) or Filtered subset (date range + recorder dropdown)
- Informational text explaining that chunk length (BirdNET) and embedding layer/version (Perch) are fixed by the platform and do not need configuration
- Submission starts a `foundation_model_run` record with `Queued` status; toast notifies users that results will appear on this page

#### Data Model Additions

**foundation_model**
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| slug | text | e.g., `birdnet_v2_4` |
| provider | text | `birdnet`, `perch`, etc. |
| version | text | BirdNET is `2.4`, Perch is `2.0` |
| display_name | text | "BirdNET" |
| description | text | Optional marketing copy |
| default_confidence_threshold | numeric | 0.10 for both |
| created_at/updated_at | timestamptz | |

**foundation_model_run**
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| foundation_model_id | uuid (FK) | references `foundation_model` |
| dataset_id | uuid (FK) | |
| requested_by | uuid (FK) | user |
| status | enum | `queued`, `running`, `post_processing`, `completed`, `failed` |
| confidence_threshold | numeric | user-provided or default 0.10 |
| scope | jsonb | filters applied (date range, recorder IDs) |
| classification_csv_path | text | storage pointer |
| embedding_store_key | text | references existing embedding schema |
| summary | jsonb | aggregated counts shown in SpeciesSummaryTable |
| started_at/completed_at | timestamptz | |
| error | jsonb | present when status = failed |

**foundation_model_run_species**
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| foundation_model_run_id | uuid (FK) | |
| gbif_taxon_id | text | reused as annotation tag lookup key |
| annotation_tag_id | uuid (FK) | optional when tag already exists |
| scientific_name | text | canonical value shown in table |
| common_name_ja | text | BirdNET common name (nullable) |
| detection_count | integer | |
| avg_confidence | numeric | |

#### Tag + GBIF Handling
- When BirdNET returns a label, parse the scientific name and look up the GBIF taxon ID via the taxonomy service; if lookup fails, store only the scientific name
- Create or update an Annotation Tag keyed by `gbif_taxon_id`, so downstream APs can reuse the same tag object
- Store BirdNET's Japanese label (when available) on `foundation_model_run_species.common_name_ja`; Perch rows will omit this field for now

#### Embeddings
- Run pipeline writes embeddings to the existing dataset embedding store schema (no new tables) using `foundation_model_run.embedding_store_key` to reference the stored vectors
- Because each run already decodes the clips, embeddings are produced alongside classification without extra compute passes

---

### 10. Species Filter UI

#### Overview
The Species Filter system uses geographic and temporal occurrence data to filter foundation model detections. After a foundation model run completes, users can apply filters (e.g., BirdNET Geo) to identify species that are unlikely to occur at the recording location and time. This helps reduce false positives from species that are geographically or seasonally impossible.

#### Backend API Integration
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/species-filters/` | GET | List available filters (e.g., BirdNET Geo v2.4) |
| `/runs/{run_uuid}/species-filter-applications/apply` | POST | Apply filter to run with threshold |
| `/runs/{run_uuid}/species-filter-applications/` | GET | List applied filters for run |
| `/runs/{run_uuid}/species-filter-applications/{uuid}` | GET | Get filter application details |
| `/runs/{run_uuid}/species-filter-applications/{uuid}/progress` | GET | Poll filter processing progress |
| `/runs/{run_uuid}/detections?filter_uuid={uuid}&include_excluded={bool}` | GET | Get filtered detection results |

---

#### 10.1 Apply Species Filter Dialog

**Trigger Points**
- Post-run completion notification: "Run complete! Apply species filter?" button
- Run detail header: "Apply Filter" button (visible when run status = completed)
- Run history drawer: "Apply Filter" action in each completed run row

**Dialog Layout**
```
+--------------------------------------------------+
| Apply Species Filter                     [X]      |
+--------------------------------------------------+
| Filter species detections based on geographic    |
| and temporal occurrence probability data.         |
+--------------------------------------------------+
| Select Filter                                     |
| +----------------------------------------------+ |
| | ( ) BirdNET Geo v2.4                         | |
| |     Uses BirdNET's geographic occurrence     | |
| |     model based on eBird data. Requires      | |
| |     location coordinates and recording date. | |
| +----------------------------------------------+ |
+--------------------------------------------------+
| Occurrence Threshold                              |
| [=======|------------------] 3%                   |
| Species with occurrence probability below this   |
| threshold will be excluded.                       |
|                                                   |
| Suggested thresholds:                             |
| - 1%: Very permissive (keep rare visitors)       |
| - 3%: Recommended (default, balanced filtering)  |
| - 10%: Strict (only common species)              |
+--------------------------------------------------+
| Apply Scope                                       |
| [x] Apply to all detections                       |
| [ ] Apply to unreviewed detections only           |
+--------------------------------------------------+
| /!\ Location Data Warning                         |
| 23 recordings (15%) lack location coordinates.   |
| Detections from these recordings will be         |
| skipped by the filter.                           |
+--------------------------------------------------+
|                          [Cancel] [Apply Filter]  |
+--------------------------------------------------+
```

**Components**

**FilterSelectionRadioGroup**
- Lists available filters from `GET /species-filters/`
- Each option shows:
  - Filter name + version badge
  - Description text (line-clamp-2)
  - Requirements icons: MapPin (location), Calendar (date)
  - Provider badge (e.g., "BirdNET", "eBird")
- Selected state: emerald border + background

**ThresholdSlider**
- Range: 0% to 100%
- Step: 1%
- Default: from `filter.default_threshold` (typically 3%)
- Tick marks at 1%, 3%, 5%, 10%, 25%, 50%
- Current value displayed prominently
- Color gradient: green (permissive) to orange (strict)

**ScopeCheckbox**
- `apply_to_all_detections: true` (default)
- When unchecked, only affects `review_status = unreviewed`

**LocationDataWarning**
- Displayed when recordings lack coordinates
- Shows count and percentage of affected recordings
- Icon: AlertTriangle (yellow)
- Collapsible details showing affected recording names

**Empty State (No Filters Available)**
```
+--------------------------------------------------+
| Apply Species Filter                     [X]      |
+--------------------------------------------------+
| [Globe icon]                                      |
| No species filters available                      |
| Contact your administrator to enable geographic   |
| occurrence filtering for your instance.           |
|                                        [Close]    |
+--------------------------------------------------+
```

---

#### 10.2 Filter Application Progress

**Layout (Inline in Run Detail)**
```
+--------------------------------------------------+
| Applying Species Filter...                        |
| BirdNET Geo v2.4 | Threshold: 3%                 |
+--------------------------------------------------+
| [========================================] 67%    |
| Processing 1,340 / 2,000 detections               |
+--------------------------------------------------+
| Live Statistics                                   |
| +------------+ +------------+ +------------+      |
| | Included   | | Excluded   | | Pass Rate  |      |
| | 892        | | 448        | | 66.6%      |      |
| +------------+ +------------+ +------------+      |
+--------------------------------------------------+
|                                        [Cancel]   |
+--------------------------------------------------+
```

**Components**

**FilterProgressCard**
- Filter name + version
- Threshold display
- Animated progress bar
- Detection count: processed / total
- Estimated time remaining (when available)
- Status badge: `pending`, `running`, `completed`, `failed`, `cancelled`

**LiveStatisticsGrid**
- Three stat boxes updated in real-time
- Included: Count with CheckCircle icon (emerald)
- Excluded: Count with XCircle icon (stone)
- Pass Rate: Percentage with PieChart icon
- Uses optimistic updates during polling

**ProgressPolling**
- Poll `GET /runs/{uuid}/species-filter-applications/{filter_uuid}/progress`
- Interval: 2000ms while status = `running`
- Auto-stop when status = `completed` or `failed`
- Show error panel with retry button on failure

**Status Color Scheme**
| Status | Color |
|--------|-------|
| Pending | stone-200/stone-700 |
| Running | blue-100/blue-700 (animated pulse) |
| Completed | emerald-100/emerald-700 |
| Failed | red-100/red-700 |
| Cancelled | stone-300/stone-600 |

---

#### 10.3 Filter Summary Panel

**Layout (Sidebar in Detection Results View)**
```
+----------------------------------+
| Species Filter Applied           |
| BirdNET Geo v2.4                 |
+----------------------------------+
| Threshold: 3%                    |
| Applied: 2 hours ago             |
+----------------------------------+
|         [Pie Chart]              |
|      Included: 1,542 (77%)       |
|      Excluded: 458 (23%)         |
+----------------------------------+
| Statistics                       |
| Total Detections: 2,000          |
| Included: 1,542                  |
| Excluded: 458                    |
| Pass Rate: 77.1%                 |
+----------------------------------+
| Top Excluded Species             |
| - Turdus migratorius (45)        |
| - Zenaida macroura (38)          |
| - Sturnus vulgaris (31)          |
+----------------------------------+
| [Re-apply with different        ]|
| [threshold                      ]|
+----------------------------------+
```

**Components**

**FilterSummaryCard**
- Collapsible panel on right side of detection results
- Shows filter metadata: name, version, threshold, applied time
- Mini pie chart (Included vs Excluded)
- Key statistics

**ExcludedSpeciesList**
- Top 5 most excluded species
- Each row: scientific name + exclusion count
- Click to filter detection table to that species
- "View all excluded" expands to full modal

**ReapplyButton**
- Opens simplified dialog with only threshold slider
- Pre-filled with current filter selection
- Warning: "This will replace the existing filter application"

---

#### 10.4 Detection Results with Filter

**Layout Updates**
```
+--------------------------------------------------+
| Detections                                        |
| +-------------+ +-------------------+ +--------+  |
| | Filter: v   | | Show: All v       | | Export |  |
| | BirdNET Geo | | Included Only     | +--------+  |
| |             | | Excluded Only     |             |
| |  No Filter  | | All               |             |
| +-------------+ +-------------------+             |
+--------------------------------------------------+
| +------+------+---------+--------+-------+------+ |
| | Spec | Conf | Species | Review | Incl. | Prob | |
| +------+------+---------+--------+-------+------+ |
| | [img]| 0.92 | Parus   | Unrevi | [Y]   | 45%  | |
| |      |      | major   | ewed   |       |      | |
| +------+------+---------+--------+-------+------+ |
| | [img]| 0.85 | Turdus  | Unrevi | [N]   | 0.2% | | <- grayed out row
| |      |      | migrat  | ewed   |       |      | |
| +------+------+---------+--------+-------+------+ |
| | [img]| 0.78 | Sitta   | Confir | [Y]   | 78%  | |
| |      |      | europae | med    |       |      | |
| +------+------+---------+--------+-------+------+ |
+--------------------------------------------------+
```

**New Column Definitions**

**Included Column ("Incl.")**
- Width: 60px
- Header: Filter icon
- Values:
  - `[Y]`: CheckCircle icon, emerald color (is_included = true)
  - `[N]`: XCircle icon, stone color (is_included = false)
  - `[-]`: Minus icon, stone color (no filter applied or skipped)
- Sortable: Yes

**Occurrence Probability Column ("Prob")**
- Width: 80px
- Header: "Occur. %" or just "%"
- Values: Percentage with 1 decimal (e.g., "45.2%")
- Visual: Mini progress bar background
- Color: Red (<3%), Yellow (3-10%), Green (>10%)
- Sortable: Yes
- Only shown when filter is selected

**Filter Selector Dropdown**
- Lists applied filter applications for the run
- Each option shows: filter name + applied timestamp
- "No Filter" option to view all detections without filter overlay
- Badge showing pass rate next to each filter option

**Show Toggle Dropdown**
- "All": Show all detections (excluded ones grayed out)
- "Included Only": Hide excluded detections entirely
- "Excluded Only": Show only excluded detections

**Excluded Row Styling**
```css
/* Excluded detection row */
.detection-row-excluded {
  opacity: 0.5;
  background-color: var(--stone-50); /* Light mode */
  background-color: var(--stone-900); /* Dark mode */
}

.detection-row-excluded .species-name {
  text-decoration: line-through;
  color: var(--stone-500);
}
```

**Bulk Actions with Filter**
- "Reject All Excluded" button: Sets review_status = rejected for all excluded detections
- Confirmation dialog: "Mark 458 excluded detections as rejected?"
- Success toast: "458 detections marked as rejected"

---

#### 10.5 Multiple Filter Applications

**Filter History Dropdown**
```
+--------------------------------------------------+
| Applied Filters for This Run                      |
+--------------------------------------------------+
| +----------------------------------------------+ |
| | BirdNET Geo v2.4 @ 3%          [Active] [v]  | |
| | Applied 2h ago by @user                       | |
| | Included: 1,542 | Excluded: 458 | 77.1%      | |
| +----------------------------------------------+ |
| | BirdNET Geo v2.4 @ 10%                   [v] | |
| | Applied 3h ago by @user                       | |
| | Included: 1,234 | Excluded: 766 | 61.7%      | |
| +----------------------------------------------+ |
|                           [Apply New Filter]     |
+--------------------------------------------------+
```

**Comparison View**
- Side-by-side comparison of two filter applications
- Venn diagram showing overlap
- Table of species that differ between filters
- "Species only included in Filter A", "Only in B", "In both"

**Filter Application Card**
- Shows filter name, threshold, applied timestamp
- Active filter highlighted with emerald border
- Click to switch active filter
- Delete button (with confirmation)

---

#### 10.6 User Flow: Applying and Viewing Species Filters

**Flow 1: Apply Filter After Run Completion**
1. Foundation model run completes
2. Toast notification: "Run complete! 2,000 detections found. Apply species filter?"
3. User clicks "Apply Filter" button
4. ApplySpeciesFilterDialog opens
5. User selects BirdNET Geo filter
6. User adjusts threshold (default 3%)
7. User clicks "Apply Filter"
8. Dialog closes, progress card appears inline
9. Progress updates every 2s
10. On completion, detection table refreshes with filter columns

**Flow 2: View Filtered Results**
1. Navigate to run detail / detection results
2. Filter selector dropdown shows applied filters
3. Select filter to activate
4. Table updates: new columns appear (Included, Occur. %)
5. Excluded rows shown grayed out
6. Toggle "Included Only" to hide excluded
7. Review included detections
8. Optionally bulk-reject excluded detections

**Flow 3: Re-apply with Different Threshold**
1. From Filter Summary Panel, click "Re-apply with different threshold"
2. Simplified dialog opens with threshold slider only
3. Adjust threshold (e.g., 3% to 10%)
4. Click "Apply"
5. New filter application created
6. Old filter remains in history for comparison
7. New filter becomes active

**Flow 4: Compare Filter Results**
1. From filter dropdown, click "Compare Filters"
2. CompareFiltersDialog opens
3. Select two filter applications to compare
4. View side-by-side statistics
5. See species that differ between thresholds
6. Decide which threshold to use for final review

---

#### 10.7 Component Specifications

**ApplySpeciesFilterDialog**
```typescript
interface ApplySpeciesFilterDialogProps {
  runUuid: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFilterApplied: (application: SpeciesFilterApplication) => void;
}
```

**FilterProgressCard**
```typescript
interface FilterProgressCardProps {
  runUuid: string;
  applicationUuid: string;
  onComplete: () => void;
  onCancel: () => void;
}
```

**FilterSummaryPanel**
```typescript
interface FilterSummaryPanelProps {
  application: SpeciesFilterApplication;
  onReapply: (threshold: number) => void;
  onViewExcluded: () => void;
}
```

**DetectionTableWithFilter**
```typescript
interface DetectionTableWithFilterProps {
  runUuid: string;
  activeFilterUuid: string | null;
  showMode: 'all' | 'included_only' | 'excluded_only';
  onFilterChange: (filterUuid: string | null) => void;
  onShowModeChange: (mode: ShowMode) => void;
}
```

**FilterComparisonDialog**
```typescript
interface FilterComparisonDialogProps {
  runUuid: string;
  applications: SpeciesFilterApplication[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}
```

---

#### 10.8 State Management Additions

**Server State (React Query)**
```typescript
// Available species filters
["species_filters"]

// Filter applications for a run
["foundation_model_run", runUuid, "filter_applications"]

// Single filter application
["foundation_model_run", runUuid, "filter_application", applicationUuid]

// Filter application progress (with refetchInterval during running)
["foundation_model_run", runUuid, "filter_application", applicationUuid, "progress"]

// Detections with filter applied
["foundation_model_run", runUuid, "detections", { filterUuid, includeExcluded }]
```

**Local State**
```typescript
interface FilterUIState {
  // Currently selected filter for viewing
  activeFilterUuid: string | null;

  // Detection display mode
  showMode: 'all' | 'included_only' | 'excluded_only';

  // Dialog states
  applyDialogOpen: boolean;
  compareDialogOpen: boolean;

  // Comparison selection
  comparisonFilterUuids: [string, string] | null;
}
```

---

#### 10.9 Data Model Reference

**species_filter**
| Column | Type | Notes |
|--------|------|-------|
| uuid | uuid (PK) | |
| slug | text | e.g., `birdnet-geo-v2-4` |
| display_name | text | "BirdNET Geo" |
| provider | text | `birdnet`, `ebird` |
| version | text | "2.4" |
| description | text | Optional |
| filter_type | enum | `geographic`, `occurrence`, `custom` |
| default_threshold | numeric | 0.03 (3%) |
| requires_location | bool | True for geographic filters |
| requires_date | bool | True for temporal filters |
| is_active | bool | |

**species_filter_application**
| Column | Type | Notes |
|--------|------|-------|
| uuid | uuid (PK) | |
| foundation_model_run_id | int (FK) | |
| species_filter_id | int (FK) | |
| threshold | numeric | User-specified threshold |
| apply_to_all_detections | bool | |
| status | enum | `pending`, `running`, `completed`, `failed`, `cancelled` |
| progress | numeric | 0.0 to 1.0 |
| total_detections | int | |
| filtered_detections | int | Passed filter (included) |
| excluded_detections | int | Failed filter |
| applied_by_id | uuid (FK) | User |
| started_on | timestamptz | |
| completed_on | timestamptz | |
| error | jsonb | |

**species_filter_mask**
| Column | Type | Notes |
|--------|------|-------|
| id | int (PK) | |
| species_filter_application_id | int (FK) | |
| clip_prediction_id | int (FK) | |
| tag_id | int (FK) | Species tag |
| is_included | bool | Passed threshold check |
| occurrence_probability | numeric | From filter model |
| exclusion_reason | text | e.g., "below_threshold" |

---

#### 10.10 Accessibility Considerations

**Keyboard Navigation**
- Filter selector dropdown: Arrow keys, Enter to select
- Threshold slider: Arrow keys for 1% increments, Page Up/Down for 10%
- Dialog: Tab through fields, Escape to close
- Excluded row indication: Screen reader announces "Excluded by species filter"

**Screen Reader Announcements**
- Filter application start: "Applying BirdNET Geo filter at 3% threshold"
- Progress updates: "Processing 67%, 448 detections excluded so far"
- Completion: "Filter complete. 77% of detections passed. 458 excluded."
- Row status: "Detection excluded. Occurrence probability 0.2%"

**Color-Blind Safe**
- Excluded rows use strikethrough in addition to color
- Included/Excluded icons have distinct shapes (check vs X)
- Occurrence probability uses pattern fills in addition to color gradient

---

#### 10.11 File Structure Additions

```
front/src/app/components/species_filters/
  ApplySpeciesFilterDialog.tsx        # Main apply dialog
  FilterProgressCard.tsx              # Progress display
  FilterSummaryPanel.tsx              # Summary sidebar
  FilterSelector.tsx                  # Dropdown for filter selection
  FilterComparisonDialog.tsx          # Compare two filters
  ThresholdSlider.tsx                 # Threshold input component
  LocationWarning.tsx                 # Missing location data alert
  ExcludedSpeciesList.tsx             # Top excluded species
  index.ts                            # Exports

front/src/lib/api/species_filters.ts  # API client functions
front/src/lib/schemas/species_filters.ts  # Zod schemas
front/src/lib/types/species_filter.ts     # TypeScript types
front/src/app/store/speciesFilter.ts      # Zustand store (optional)
```

---

#### 10.12 Implementation Checklist

- [ ] Species filter schemas and types
- [ ] API client for species filter endpoints
- [ ] ApplySpeciesFilterDialog component
- [ ] ThresholdSlider component
- [ ] LocationWarning component
- [ ] FilterProgressCard with polling
- [ ] FilterSummaryPanel component
- [ ] Detection table filter columns (Included, Occur. %)
- [ ] Filter selector dropdown
- [ ] Show mode toggle (All/Included/Excluded)
- [ ] Excluded row styling
- [ ] Bulk reject excluded action
- [ ] Filter comparison dialog
- [ ] React Query hooks for filter state
- [ ] Accessibility testing
- [ ] Mobile responsive layouts

---

## Responsive Behavior

### Breakpoints
- **Mobile** (< 768px): Single column layout, stacked cards
- **Tablet** (768px - 1024px): 2-column grid for cards
- **Desktop** (> 1024px): 3-4 column grid, side panels

### Grid Specifications
| Component | Mobile | Tablet | Desktop |
|-----------|--------|--------|---------|
| Project Cards | 1 col | 2 col | 3 col |
| Reference Sound Cards | 1 col | 2 col | 4 col |
| Session Cards | 1 col | 2 col | 3 col |
| Model Cards | 1 col | 1 col | 2 col |
| Result Cards | 2 col | 3 col | 4 col |
| Prediction Cards | 2 col | 3 col | 4 col |
| Detection Table | Full width, horizontal scroll on mobile |
| Filter Summary Panel | Full width modal (mobile) | Sidebar 320px (tablet+) |
| Filter Stat Boxes | 1 col stacked | 3 col inline | 3 col inline |

---

## Accessibility

### Keyboard Navigation
- All interactive elements focusable with Tab
- Enter/Space to activate buttons
- Arrow keys for navigation in grids
- Escape to close dialogs
- Custom shortcuts in labeling mode (P, N, U, S)

### Screen Reader Support
- Descriptive button labels
- Status announcements on changes
- Progress bar percentage announcements
- Form field labels and error messages

### Color Contrast
- All text meets WCAG 2.1 AA contrast requirements
- Status badges use icons in addition to color
- Focus indicators visible in both light and dark modes

---

## State Management

### Server State (React Query)
- ML Projects list: `["ml_projects", filter]`
- ML Project detail: `["ml_project", uuid]`
- Reference Sounds: `["ml_project", uuid, "reference_sounds"]`
- Search Sessions: `["ml_project", uuid, "search_sessions"]`
- Search Results: `["ml_project", uuid, "search_session", sessionUuid, "results"]`
- Custom Models: `["ml_project", uuid, "custom_models"]`
- Inference Batches: `["ml_project", uuid, "inference_batches"]`
- Species Filters: `["species_filters"]`
- Filter Applications: `["foundation_model_run", runUuid, "filter_applications"]`
- Filter Progress: `["foundation_model_run", runUuid, "filter_application", appUuid, "progress"]`
- Filtered Detections: `["foundation_model_run", runUuid, "detections", { filterUuid, includeExcluded }]`

### Local State
- Selected result index in labeling mode
- Filter values (status, label, review status)
- Pagination (page number)
- Dialog open states
- Expanded batch IDs
- Active species filter UUID for detection view
- Detection show mode (all, included_only, excluded_only)

### Context
- `MLProjectContext`: Current project data passed to child components

---

## Performance Considerations

### Optimizations
1. Pagination for all lists (default page size: 12-24)
2. Spectrogram lazy loading with placeholders
3. Auto-refresh intervals only when needed (running batches: 5s)
4. Query invalidation on mutations
5. Optimistic updates for labeling

### Loading States
- Skeleton loaders for cards
- Spinner for actions
- Progress bars for long-running operations

---

## File Structure

```
front/src/app/(base)/ml-projects/
  page.tsx                                    # List page
  [ml_project_uuid]/
    layout.tsx                                # Detail layout with tabs
    page.tsx                                  # Overview tab
    context.tsx                               # MLProjectContext
    reference-sounds/
      page.tsx                                # Reference sounds management
    search/
      page.tsx                                # Search sessions list
      [session_uuid]/
        page.tsx                              # Labeling interface
    models/
      page.tsx                                # Custom models management
    inference/
      page.tsx                                # Inference batches
      [batch_uuid]/
        page.tsx                              # Batch detail (optional)

front/src/app/components/ml_projects/
  MLProjectCard.tsx                           # Project card component
  MLProjectCreate.tsx                         # Create dialog
  ReferenceSoundCard.tsx                      # Reference sound card
  ReferenceSoundFromXenoCanto.tsx             # Xeno-Canto dialog
  ReferenceSoundFromClip.tsx                  # Clip dialog
  SearchSessionCreate.tsx                     # Create session dialog
  SearchResultGrid.tsx                        # Results grid component
  LabelingInterface.tsx                       # Labeling panel
  CustomModelCard.tsx                         # Model card component
  InferenceBatchCard.tsx                      # Batch card component
  PredictionReviewGrid.tsx                    # Predictions grid
  index.ts                                    # Exports
```

---

## Implementation Status

Based on the codebase analysis, the following components are already implemented:

### Completed
- [x] ML Projects list page with filtering
- [x] Create project dialog
- [x] Project detail layout with tabs
- [x] Overview page with workflow progress
- [x] Reference sounds page with Xeno-Canto/Clip dialogs
- [x] Search sessions page with create dialog
- [x] Search session detail with labeling interface
- [x] Models page with create/train/deploy workflow
- [x] Inference page with batch management and prediction review

### Potential Enhancements
- [ ] Actual spectrogram rendering (currently placeholder)
- [ ] Audio playback integration
- [ ] Bulk labeling operations
- [ ] Export functionality
- [ ] Model comparison views
- [ ] Advanced filtering options
- [ ] Batch operations for reference sounds

### Species Filter UI (New - Section 10)
- [ ] Species filter schemas and types
- [ ] API client for species filter endpoints
- [ ] ApplySpeciesFilterDialog component
- [ ] ThresholdSlider component
- [ ] LocationWarning component
- [ ] FilterProgressCard with polling
- [ ] FilterSummaryPanel component
- [ ] Detection table filter columns (Included, Occur. %)
- [ ] Filter selector dropdown
- [ ] Show mode toggle (All/Included/Excluded)
- [ ] Excluded row styling
- [ ] Bulk reject excluded action
- [ ] Filter comparison dialog
- [ ] React Query hooks for filter state
- [ ] Accessibility testing
- [ ] Mobile responsive layouts

---

## Appendix: API Endpoints

### ML Projects
- `GET /api/ml-projects` - List projects
- `POST /api/ml-projects` - Create project
- `GET /api/ml-projects/:uuid` - Get project
- `PATCH /api/ml-projects/:uuid` - Update project
- `DELETE /api/ml-projects/:uuid` - Delete project

### Reference Sounds
- `GET /api/ml-projects/:uuid/reference-sounds` - List sounds
- `POST /api/ml-projects/:uuid/reference-sounds/xeno-canto` - Add from Xeno-Canto
- `POST /api/ml-projects/:uuid/reference-sounds/clip` - Add from clip
- `PATCH /api/ml-projects/:uuid/reference-sounds/:soundUuid/toggle` - Toggle active
- `DELETE /api/ml-projects/:uuid/reference-sounds/:soundUuid` - Delete sound

### Search Sessions
- `GET /api/ml-projects/:uuid/search-sessions` - List sessions
- `POST /api/ml-projects/:uuid/search-sessions` - Create session
- `GET /api/ml-projects/:uuid/search-sessions/:sessionUuid` - Get session
- `POST /api/ml-projects/:uuid/search-sessions/:sessionUuid/execute` - Execute search
- `GET /api/ml-projects/:uuid/search-sessions/:sessionUuid/results` - Get results
- `POST /api/ml-projects/:uuid/search-sessions/:sessionUuid/results/:resultUuid/label` - Label result
- `POST /api/ml-projects/:uuid/search-sessions/:sessionUuid/complete` - Mark complete

### Custom Models
- `GET /api/ml-projects/:uuid/custom-models` - List models
- `POST /api/ml-projects/:uuid/custom-models` - Create model
- `POST /api/ml-projects/:uuid/custom-models/:modelUuid/train` - Start training
- `POST /api/ml-projects/:uuid/custom-models/:modelUuid/deploy` - Deploy model
- `POST /api/ml-projects/:uuid/custom-models/:modelUuid/archive` - Archive model

### Inference Batches
- `GET /api/ml-projects/:uuid/inference-batches` - List batches
- `POST /api/ml-projects/:uuid/inference-batches` - Create batch
- `POST /api/ml-projects/:uuid/inference-batches/:batchUuid/start` - Start batch
- `POST /api/ml-projects/:uuid/inference-batches/:batchUuid/cancel` - Cancel batch
- `GET /api/ml-projects/:uuid/inference-batches/:batchUuid/predictions` - Get predictions
- `POST /api/ml-projects/:uuid/inference-batches/:batchUuid/predictions/:predUuid/review` - Review prediction

### Species Filters
- `GET /api/species-filters/` - List available species filters
- `POST /api/runs/:runUuid/species-filter-applications/apply` - Apply filter to run
- `GET /api/runs/:runUuid/species-filter-applications/` - List filter applications for run
- `GET /api/runs/:runUuid/species-filter-applications/:filterUuid` - Get filter application details
- `GET /api/runs/:runUuid/species-filter-applications/:filterUuid/progress` - Get filter progress
- `GET /api/runs/:runUuid/detections?filter_uuid={uuid}&include_excluded={bool}` - Get filtered detections
