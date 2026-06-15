# Review-result layout redesign

**Status:** Design approved (brainstorming complete)
**Date:** 2026-06-15
**Branch:** `feature/remote-git`
**Scope:** Frontend only — no backend changes.

## Problem

The current review-result panel (`frontend/src/components/ReviewPanel.vue`) is
hard to navigate:

- The 3-row sticky tab bar at the top horizontally scrolls and truncates
  long paths to 200 px, losing orientation across 15+ files.
- Files are stacked into a single vertical article feed; switching to a
  later file means scrolling past every earlier file's diff and inline
  finding cards.
- The only file-switching mechanism is a `scrollTo` jump triggered by
  the tab bar, augmented by an `IntersectionObserver` scroll-spy.

This redesign makes the file tree the primary navigation surface and
turns the review-result body into a single-file viewer, so a user can
read one file's diff + findings without context-switching.

## Decisions (from brainstorming)

| # | Decision | Rationale |
|---|---|---|
| 1 | **A** — the sticky tab bar is the worst pain point (not the feed, the inline cards, or the nav chrome) | Confirmed by user click on the labeled wireframe |
| 2 | **1a** — left vertical tree + single-file viewer (true GitHub PR pattern) | B transforms structurally; user explicitly chose 1a over 1b (tree-as-TOC) |
| 3 | **B** — 2-col layout `240px tree | 1fr viewer`; history becomes a header-button drawer | Chose over A (3-col, viewer squeezed to ~720 px) and C (stack tree + history, both squeezed) |
| 4 | **T2** — folder-grouped, collapsible tree | Chose over flat list (T1) for review repos with nested directories |

## Architecture

### New components

| File | Responsibility |
|---|---|
| `frontend/src/components/ReviewTree.vue` | Left 240 px file tree. Props: `files`, `activeFile`, `expandedFolders: Set<string>`, `findingsByFile: (path) => number`. Emits: `select(path)`, `toggle-folder(folder)`. Internally groups by `path.split('/')`. |
| `frontend/src/components/HistoryDrawer.vue` | Right-side slide-in drawer wrapping the existing `HistoryList`. Props: `open`, `items`, `total`, `activeId`. Emits: `update:open`, `open(id)`, `refresh`, `remove(id)`. |
| `frontend/src/components/ReviewTreeHeader.vue` | Top of tree: file count + status filter chips (All / Added / Modified / Deleted) — moved from old ReviewPanel. |

### Changed components

| File | Changes |
|---|---|
| `frontend/src/App.vue` | Grid changes to `lg:grid-cols-[240px,1fr]`. Right `<aside>` (history + tips) is deleted. Header gets two new buttons: "📜 History" and "⋯" (tips). Renders `<ReviewTree>`, `<ReviewPanel>`, `<HistoryDrawer>`. |
| `frontend/src/components/ReviewPanel.vue` | Transformed from "article feed" to "single-file viewer". Props: `file` (single), `findings` (for that file), `status`. Renders the file's diff + inline finding cards (preserves the C decision). Removed: sticky tab bar, `IntersectionObserver` scroll-spy, `gotoFile()`, expand/collapse state, status filter chips, bottom legend. |
| `frontend/src/components/Header.vue` | Two new buttons: "📜 History (N)" (hidden when `history.total === 0` — i.e. no review has ever been done) and "⋯" (shown only when `!currentReview` — input mode, before any review is running; hidden during review so it doesn't distract). Each toggles its drawer open. |
| `frontend/src/composables/useReview.js` | Adds two reactive refs: `activeFile: Ref<string|null>`, `treeExpanded: Ref<Set<string>>`. Wires localStorage persistence (see Persistence). |

### Removed (no replacement)

- The sticky file-tab-bar block in `ReviewPanel.vue`
- The `IntersectionObserver` scroll-spy
- The `expandAll` / `collapseAll` buttons and `collapsedFiles` state
- The status filter chip row (moved to tree header)
- The bottom legend strip (added/modified/context color swatches)
- The right `<aside>` block in `App.vue` (history + tips)

## Data flow

```
App.vue
  ├─ useReview.activeFile (Ref<string|null>)  ← new
  ├─ useReview.treeExpanded (Ref<Set<string>>)  ← new
  ├─ useReview.historyOpen (local ref)         ← new
  ├─ useReview.tipsOpen (local ref)            ← new
  │
  ├─ <Header>
  │    ├─ "📜 History" → review.historyOpen = !review.historyOpen
  │    └─ "⋯" tips    → review.tipsOpen = !review.tipsOpen
  │
  ├─ <ReviewTreeHeader :statusCounts :statusFilter @update:statusFilter>
  ├─ <ReviewTree :files :activeFile :expanded :findingsByFile
  │                @select="review.activeFile = path"
  │                @toggle-folder="review.treeExpanded toggle" />
  │
  └─ <ReviewPanel :file="activeFile ? files.find(f) : null"
                   :findings="findingsFor(activeFile)"
                   :status="status" />

<HistoryDrawer :open="historyOpen" :items :total :activeId
               @update:open="historyOpen = $event"
               @open="review.open"
               @refresh="history.refresh"
               @remove="review.removeHistory" />

<TipsPopover :open="tipsOpen" @update:open="tipsOpen = $event" />
```

The tree emits `select(path)`; the parent updates `activeFile`. The viewer
re-renders when `activeFile` changes. The `scrollTop` of the viewer
container resets to 0 on every `activeFile` change.

## Drawer behavior

| Aspect | Choice |
|---|---|
| Open direction | Right slide-in, covers viewer (no overlay dim) |
| Width | 400 px (was 320 px in the aside) |
| Animation | `translate-x-full` → `translate-x-0`, 200 ms ease-out |
| Close triggers | (1) X button, (2) click outside drawer on viewer, (3) `Esc` key |
| Focus trap | First focusable element on open; `Esc` listener on `document` |
| Default state | Closed; opens only via Header button |
| Mutual exclusion | History drawer and tips drawer are mutually exclusive (both toggled from Header right side). The mobile tree drawer (☰) is independent — opening it does not close history/tips. |

## Mobile / narrow viewports

| Breakpoint | Tree | History | Viewer |
|---|---|---|---|
| ≥ 1024 px | 240 px left column | header button → right drawer | 1 fr |
| 768 – 1023 px | 240 px left drawer (☰) | header button → right drawer | 1 fr |
| < 768 px | 240 px left drawer (☰) | full-screen drawer | 1 fr |

Below 1024 px, Header shows a "☰" button that toggles the tree drawer.
Tree and history drawers are independent instances (separate animation
state).

## Persistence (localStorage)

| State | Persisted? | Key |
|---|---|---|
| `useReview.activeFile` | Yes | `codereview.review.activeFile` |
| `useReview.treeExpanded` | Yes | `codereview.review.treeExpanded` (JSON array) |
| `historyOpen` / `tipsOpen` | No | — (transient UI state) |
| `apiKey` (existing) | Yes | (unchanged) |

**Guards:**
- Persistence writes only after a review has at least one file.
- On reload, if `activeFile` references a path not in the current files list, fall back to the default (see below) and clear the stored key.
- `treeExpanded` is stored as a JSON array of folder paths; unknown folders are silently dropped on load.

**Default `activeFile`:**
1. First file with at least one finding
2. Otherwise first file with status `added` or `modified`
3. Otherwise first file in the list

## Tree status filter

`ReviewTreeHeader` exposes chips: All / Added / Modified / Deleted. The
tree filters files (and any folder whose remaining files are empty
after filtering is hidden). Finding-count badges on the tree reflect
**unfiltered** counts (the chip filters files, not findings inside a
visible file — that distinction matters for "which file has findings
worth checking").

## Loading / error / empty states

| State | ReviewPanel | Tree |
|---|---|---|
| `!currentReview` | not rendered | not rendered |
| `status='connecting'` / `'streaming'` | renders current `activeFile` diff; findings stream in | tree lists all files (backend sends files before findings) |
| `status='completed'` + 0 findings | `t('review.noFindingsInReview')` | tree lists all files, no badges |
| `status='completed'` + 0 files | hidden; banner "no files changed" | not rendered |
| `status='failed'` | existing red error banner in App.vue | tree still renders files |
| `activeFile` not in current files (race) | fallback to default + `console.warn` | tree active highlight follows |

## Transitions

- Viewer content **does not** animate (no fade) — animation here would
  read as loading. Hard replace.
- On every `activeFile` change, viewer `scrollTop` resets to 0.
- Tree active highlight uses `transition-colors 150 ms`.
- CodeView internal finding cards unchanged.

## Testing

### Unit (vitest)

| File | What |
|---|---|
| `ReviewTree.test.js` (new) | (1) `path.split('/')` grouping correct, (2) nested folder hierarchy correct, (3) status filter hides non-matching files, (4) empty folders (post-filter) hidden, (5) toggle folder expansion, (6) click file emits `select(path)`, (7) finding badges are unfiltered counts |
| `HistoryDrawer.test.js` (new) | (1) `Esc` closes, (2) X button emits `update:open(false)`, (3) focus lands on first focusable on open, (4) renders `HistoryList` child |
| `ReviewPanel.test.js` (rewrite) | (1) renders single file diff + findings, (2) empty state on 0 findings, (3) viewer header shows path + status + +N/-M. **Remove** old tests for sticky tab, scrollspy, expand/collapse. |
| `useReview.test.js` (extend) | (1) `activeFile` initial = first file with findings, (2) `activeFile` persists to localStorage, (3) reload validates path against current files |
| `App.test.js` (if exists / new) | (1) < 1024 px → tree in drawer, (2) ≥ 1024 px → tree in column |

### Manual (docs/manual-test-review-layout.md, new)

- [ ] 12-file review at > 1024 px: tree + viewer in two columns
- [ ] 5 findings across 3 files: tree badges correct, active file highlighted
- [ ] Click `tests/test_auth.py` in tree: viewer switches, scrollTop = 0
- [ ] Click Header "📜 History": drawer slides in from right, focus on first item
- [ ] `Esc` / click viewer / click X: drawer closes
- [ ] Resize to 800 px: tree in drawer, "☰" appears
- [ ] Resize to 360 px: viewer still readable, drawers full-width
- [ ] Persistence: select a file, refresh, same file selected
- [ ] Persistence: collapse `src/`, refresh, still collapsed
- [ ] Dark mode: all colors have sufficient contrast

### Visual regression

Not automated (no Playwright/Puppeteer installed). Reviewed manually
before merge.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| History and tips drawers open simultaneously (both Header buttons) | medium | medium | Header enforces mutual exclusion in App.vue; opening one closes the other. ESC closes the most recent. |
| Stale `activeFile` references a path no longer in files | medium | low | Load-time guard falls back to default + clears localStorage key |
| Long single file (500+ lines diff) is still hard to navigate | high | medium | Out of scope for this spec. Existing inline `Jump to line` per-finding card still works. Future work: jump-to-next-finding. |
| App.vue grid change breaks responsive | low | medium | Use `lg:` breakpoint; < 1024 px falls back to single column + drawers |
| `findingsFor(path)` filter called twice in different places risks drift | low | low | Keep a single `findingsFor(path)` helper inside `ReviewPanel.vue`; do not duplicate |
| 50+ files: tree scroll performance | medium | medium | Plain `v-for`; no virtual scrolling (YAGNI). Revisit if real reviews hit 50+ |
| i18n key drift between en and zh | low | low | Add new keys to the symmetry-check list in `messages.test.js` |

## Migration

No database migration. No flag flip. No dark launch. Direct UI swap.

Commit split (clean revert per concern):

- **Commit 1** — new components and state:
  - `frontend/src/components/ReviewTree.vue` (new)
  - `frontend/src/components/HistoryDrawer.vue` (new)
  - `frontend/src/components/ReviewTreeHeader.vue` (new)
  - `frontend/src/composables/useReview.js` (added `activeFile`, `treeExpanded`)
  - `frontend/src/i18n/messages.js` + `messages.test.js` (new keys for status filter labels)
  - `frontend/src/utils/format.js` (helper: group files by folder)
- **Commit 2** — wire it in:
  - `frontend/src/App.vue` (grid change, new Header buttons, drawer mount)
  - `frontend/src/components/Header.vue` (history + tips buttons)
  - `frontend/src/components/ReviewPanel.vue` (transform to single-file viewer)
  - `frontend/src/components/HistoryList.vue` (only if it needs an "open as drawer" prop variant)

Per-commit checks (CI-clean):
- `cd backend && pytest -q` (unchanged, must still pass)
- `cd frontend && npm test` (new tests must pass)
- `cd frontend && npm run lint` (clean)
- `cd frontend && npm run build` (succeeds, async-split chunks still emitted)

## Out of scope (explicit)

- Single-file viewer internal jump-to-next-finding navigation
- Tree search box
- Virtual scrolling (defer until 50+ files is a real case)
- Resizable tree width
- Tree multi-select / batch operations
- Code review threads / inline comments
- Backend API changes

## Open questions

None — all design decisions resolved during brainstorming. Implementation
can begin.
