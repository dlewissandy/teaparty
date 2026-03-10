# Textual TUI Selection Widget Events

Research into Textual (Textualize) Python TUI framework widgets that fire events on highlight/selection change. Motivated by the dashboard screen's need to update a right-hand panel when the user navigates a project list with arrow keys, without the race conditions encountered using `DataTable.CursorMoved`.

**Context:** `projects/POC/tui/screens/dashboard.py` uses `DataTable` with a polling-based workaround (reading `cursor_row` on a timer) because `CursorMoved` fires async events that race with `clear()`/`add_row()`/`move_cursor()` calls during periodic refresh.

---

## Widget Comparison Summary

| Widget | Highlight Event | Fires on Arrow Keys | Item Data in Event | Safe to Clear + Rebuild |
|--------|----------------|--------------------|--------------------|------------------------|
| `ListView` | `Highlighted` | Yes | `event.item` (ListItem) | Mostly — `validate_index()` clamps; no confirmed spurious fire |
| `OptionList` | `OptionHighlighted` | Yes | `event.option`, `.option_id`, `.option_index` | Known layout bug in v2.0.0 (fixed in PR #5730); use `set_options()` |
| `Tree` | `NodeHighlighted` | Yes | `event.node` (TreeNode, has `.data`) | Not documented; cursor managed by `validate_cursor_line()` |
| `SelectionList` | `SelectionHighlighted` | Yes (highlight only; Space/Enter to toggle) | `event.selection`, `.index` | Inherits OptionList; same caveat |

The universal escape hatch for suppressing events during programmatic updates is `widget.prevent(MessageType)` context manager (available in Textual 0.40+).

---

## 1. ListView

**Documentation:** https://textual.textualize.io/widgets/list_view/

### Events

**`ListView.Highlighted`**
- Fires when the highlighted item changes — including on up/down arrow key navigation.
- Attributes:
  - `item: ListItem | None` — the currently highlighted item widget
  - `list_view: ListView` — the containing widget
  - `control` — alias for `list_view`
- Handler name: `on_list_view_highlighted`

**`ListView.Selected`**
- Fires only when the user explicitly selects an item (Enter key or click).
- Attributes:
  - `item: ListItem` — the selected item widget
  - `index: int` — numeric position
  - `list_view: ListView`
  - `control` — alias for `list_view`
- Handler name: `on_list_view_selected`

### Arrow Key Navigation

`Highlighted` fires reliably on every arrow key press. This is the correct event for "update another panel as user navigates."

### Getting Item Data

`ListItem` is a widget container (typically wrapping a `Label`). There is no built-in `.data` payload attached to a `ListItem`. To associate data with a list item, you must either:
- Subclass `ListItem` and add attributes, or
- Maintain a parallel list (e.g., `self._project_slugs`) indexed by position, and use `event.list_view.index` to look up the corresponding data.

```python
def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
    if event.item is None:
        return
    idx = event.list_view.index       # int | None
    if idx is not None and 0 <= idx < len(self._project_slugs):
        self._selected_project = self._project_slugs[idx]
        self._rebuild_session_table()
```

### Clearing and Rebuilding

- `clear()` removes all items and returns `AwaitRemove`.
- The `index` reactive is validated via `validate_index()`, which clamps to the valid range or sets to `None` when no items exist.
- `watch_index()` fires when `index` changes programmatically, which may trigger a `Highlighted` message.
- **Known bug (fixed Nov 2024, PR #5135):** `pop()` and `remove_items()` previously did not update the index, leaving the highlight pointing at a now-invalid row. This is fixed in Textual >= the version containing PR #5135.
- To suppress spurious `Highlighted` events during a clear/rebuild, use the `prevent()` context manager:

```python
with self.prevent(ListView.Highlighted):
    lv.clear()
    lv.extend(new_items)
```

### Use Case Fit for Dashboard

ListView is a good fit if list items are simple (label strings). The parallel-index pattern already used in `dashboard.py` (`self._project_slugs[idx]`) translates directly. The main cost is that `ListItem` carries no typed data payload — you rely on positional alignment.

---

## 2. OptionList

**Documentation:** https://textual.textualize.io/widgets/option_list/

### Events

Both events inherit from `OptionList.OptionMessage`.

**`OptionList.OptionHighlighted`**
- Fires when an option receives highlight focus — including on arrow key navigation.
- Attributes (from `OptionMessage`):
  - `option: Option` — the Option object with `.prompt` (display text) and `.id` (optional string)
  - `option_id: str | None` — the option's string identifier if set
  - `option_index: int` — numeric index
  - `option_list: OptionList` — the containing widget
  - `control` — alias for `option_list`
- Handler name: `on_option_list_option_highlighted`

**`OptionList.OptionSelected`**
- Fires only on explicit selection (Enter key).
- Same attributes as `OptionHighlighted`.
- Handler name: `on_option_list_option_selected`

### Arrow Key Navigation

`OptionHighlighted` fires on every arrow key press. This is the correct event for panel-update use cases.

**Important timing note:** Do not read `self.highlighted` inside an `on_key` handler — the highlight state may not yet reflect the key press. Always read it from within the `OptionHighlighted` event handler itself, where the state is guaranteed to be current.

### Getting Item Data

`Option` objects have:
- `option.prompt` — the displayed text (the `VisualType` passed at construction)
- `option.id` — an optional string identifier you assign at construction

The recommended pattern for associating typed data with an option is to set `id` to a string key (e.g., project slug) and look up from a dict:

```python
option_list.add_option(Option(proj.slug, id=proj.slug))
```

```python
def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
    if event.option_id:
        self._selected_project = event.option_id
        self._rebuild_session_panel()
```

This avoids the parallel-list index alignment problem entirely.

### Clearing and Rebuilding

- `clear_options()` — removes all options, returns `Self` (chainable, synchronous).
- `add_option(option)` — appends a single option or separator (`None`).
- `add_options(options)` — appends multiple options.
- `set_options(options)` — replaces all options in one call (preferred for refresh use cases).
- `highlighted` property — `int | None`, index of currently highlighted option.
- `highlighted_option` property — `Option | None`, the Option object itself.

**Known bug (v2.0.0, fixed in PR #5730):** After `clear_options()`, the widget's layout and scrollbar could fail to recalculate their height correctly. This was a regression introduced in v2.0.0 and was fixed shortly after. Pin Textual >= the version containing PR #5730 if using `clear_options()` in periodic refresh loops.

**Spurious events on clear:** Not explicitly documented, but since `clear_options()` is a programmatic state change (not a user interaction), `OptionHighlighted` should not fire during it. If the `highlighted` index becomes invalid after clearing (e.g., points beyond the new list end), Textual may reset it to 0 or `None`. To be safe, use `prevent()`:

```python
with self.prevent(OptionList.OptionHighlighted):
    option_list.set_options([Option(p.slug, id=p.slug) for p in projects])
```

Then manually restore and fire a highlight update if needed:

```python
option_list.highlighted = saved_index
```

### Use Case Fit for Dashboard

`OptionList` is arguably the best fit for the project-list panel:
- `Option(id=...)` lets you embed a string key directly — no parallel index list needed.
- `set_options()` is a single atomic call to replace all content.
- `OptionHighlighted` fires on arrow keys with the option object (and `option_id`) directly accessible from the event.
- Lighter widget than `DataTable` (no columns, no cursor types, no row keys).

---

## 3. Tree

**Documentation:** https://textual.textualize.io/widgets/tree/

### Events

**`Tree.NodeHighlighted`**
- Fires when a node becomes the cursor target — including on arrow key navigation.
- Attributes:
  - `node: TreeNode` — the highlighted node
  - `control: Tree` — the tree widget
- Handler name: `on_tree_node_highlighted`

**`Tree.NodeSelected`**
- Fires on explicit selection (Enter key or `action_select_cursor()`).
- Attributes:
  - `node: TreeNode`
  - `control: Tree`
- Handler name: `on_tree_node_selected`

### Arrow Key Navigation

`NodeHighlighted` fires on every arrow key navigation step. The `auto_expand` setting determines whether nodes also expand when navigated to.

### Getting Node Data

Each `TreeNode` carries an optional `.data` attribute of any type, set at node creation:

```python
tree.root.add("ProjectName", data=project_object)
```

```python
def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
    if event.node.data is not None:
        self._selected_project = event.node.data.slug
        self._rebuild_session_panel()
```

This is the cleanest data-attachment pattern of the three widgets — typed, arbitrary payload, no string IDs needed.

### Clearing and Rebuilding

`Tree` does not have a simple `clear()` equivalent. The typical approach is:
- Call `tree.clear()` to reset the tree to only its root node, then re-add children.
- Or remove and re-add the `Tree` widget itself (heavier).

`validate_cursor_line()` manages cursor bounds during structural changes. Whether structural rebuilds fire spurious `NodeHighlighted` events is not formally documented, but the validation logic suggests the framework attempts to keep the cursor in a valid state. Use `prevent()` as a safeguard:

```python
with self.prevent(Tree.NodeHighlighted):
    tree.clear()
    for proj in projects:
        tree.root.add(proj.slug, data=proj)
    tree.root.expand()
```

### Use Case Fit for Dashboard

`Tree` is ideal if the list has hierarchy (e.g., workgroups containing projects). For a flat project list, it adds complexity (root node, expand/collapse bindings) without benefit. For the current flat-list case, `OptionList` or `ListView` are simpler.

---

## 4. SelectionList

**Documentation:** https://textual.textualize.io/widgets/selection_list/

### Events

**`SelectionList.SelectionHighlighted`**
- Fires when a selection becomes highlighted — including on arrow key navigation.
- Attributes:
  - `selection_list: SelectionList`
  - `index: int`
  - `selection: Selection` — the Selection object
  - `selection.value` — the typed data value associated with this selection

**`SelectionList.SelectionToggled`**
- Fires when an item is checked/unchecked (Space or Enter, or programmatic `toggle()`).
- Same attributes as above.
- Note: fires once per toggled item even during bulk operations (`toggle_all()`).

**`SelectionList.SelectedChanged`**
- Fires whenever the set of checked items changes (from any cause).

### Arrow Key Navigation

Arrow keys trigger `SelectionHighlighted` only. `SelectionToggled` requires explicit user action (Space/Enter). This is an important distinction from multi-select intent: navigating does not auto-check items.

### Getting Item Data

Each `Selection` has a `.value` of a parameterized type:

```python
selection_list = SelectionList[str](
    Selection("Project Alpha", "alpha"),
    Selection("Project Beta", "beta"),
)
```

```python
def on_selection_list_selection_highlighted(
    self, event: SelectionList.SelectionHighlighted
) -> None:
    highlighted_value = event.selection.value  # "alpha" or "beta"
```

### Use Case Fit for Dashboard

`SelectionList` is designed for multi-select checkboxes (like selecting multiple items to batch-process). It is the wrong widget for a single-selection navigation list where the selected item drives panel updates. The "toggle" model adds unwanted visual and interaction complexity. Do not use `SelectionList` here.

---

## 5. The `prevent()` Context Manager (Universal Escape Hatch)

**Documentation:** https://textual.textualize.io/guide/events/

All Textual widgets support a `prevent()` context manager that temporarily suppresses posting of a specific message type. This is the canonical solution for avoiding spurious events during programmatic widget updates:

```python
# Rebuild without triggering the highlight handler
with self.prevent(OptionList.OptionHighlighted):
    option_list.set_options([...])

# Or on the widget itself:
with option_list.prevent(OptionList.OptionHighlighted):
    option_list.set_options([...])
```

This is distinct from:
- `event.stop()` — prevents the event from bubbling to parent widgets
- `event.prevent_default()` — prevents base-class handlers from running

`prevent()` is the right tool when you want a programmatic state mutation to not trigger downstream reactive handlers.

---

## 6. Recommendation for dashboard.py

The current `DataTable` + polling-on-timer approach avoids race conditions but adds latency (up to one timer tick) and complexity. The race condition root cause is that `DataTable.CursorMoved` fires as a message posted into the async event queue, which can arrive after a `clear()`/`add_row()` sequence from a concurrent timer tick has already reset the cursor.

**Recommended replacement for the project-list panel: `OptionList`**

Reasons:
1. `OptionHighlighted` fires synchronously in response to key events — no async queue race with `clear_options()`.
2. `Option(id=proj.slug)` embeds the key directly in the widget item, eliminating the parallel `self._project_slugs` list.
3. `set_options()` is a single atomic call, simpler than `clear()` + `add_row()` loop.
4. `with option_list.prevent(OptionList.OptionHighlighted)` gives a clean, explicit gate during rebuilds.
5. Lighter than `DataTable` — no column definitions, no row keys, no cursor type configuration.

**Pattern for periodic refresh with OptionList:**

```python
def _rebuild_project_list(self) -> None:
    ol = self.query_one('#project-list', OptionList)
    # Save the currently highlighted option id before rebuilding
    saved_id = ol.highlighted_option.id if ol.highlighted_option else None

    # Rebuild without triggering the highlight handler
    with ol.prevent(OptionList.OptionHighlighted):
        ol.set_options([
            Option(proj.slug, id=proj.slug)
            for proj in self.app.state_reader.projects
        ])

    # Restore highlight position
    if saved_id:
        for i, opt in enumerate(ol.options):
            if opt.id == saved_id:
                ol.highlighted = i
                break
        else:
            ol.highlighted = 0 if ol.option_count > 0 else None
    elif ol.option_count > 0:
        ol.highlighted = 0

def on_option_list_option_highlighted(
    self, event: OptionList.OptionHighlighted
) -> None:
    if event.option_list.id == 'project-list' and event.option_id:
        self._selected_project = event.option_id
        self._rebuild_session_panel()
```

---

## Sources

- [Textual ListView documentation](https://textual.textualize.io/widgets/list_view/)
- [Textual OptionList documentation](https://textual.textualize.io/widgets/option_list/)
- [Textual Tree widget documentation](https://textual.textualize.io/widgets/tree/)
- [Textual SelectionList documentation](https://textual.textualize.io/widgets/selection_list/)
- [Textual Events and Messages guide](https://textual.textualize.io/guide/events/)
- [GitHub: ListView index not updated after item removal (PR #5135, fixed Nov 2024)](https://github.com/Textualize/textual/issues/5114)
- [GitHub: OptionList not fully updating on clear since v2.0.0 (PR #5730)](https://github.com/Textualize/textual/issues/5728)
- [GitHub: OptionList highlighted property timing issue with single option](https://github.com/Textualize/textual/discussions/2857)
- [GitHub: Advice on working with ListView and ListItem (discussion #4322)](https://github.com/Textualize/textual/discussions/4322)
- [GitHub: Updating DataTable data periodically (discussion #3328)](https://github.com/Textualize/textual/discussions/3328)
- [GitHub: OptionList not designed for dynamic per-item updates (discussion #2241)](https://github.com/Textualize/textual/discussions/2241)
