# Workbench Monitor Detail Center Plan

## Goal

Move specific task monitoring details out of the narrow right dock and into the center work area.

## Target Structure

- Right panel: global monitor summary, metrics, and task list only.
- Center work area: selected task detail monitor, including graph monitor or runtime loop detail.
- Selection state: reuse `globalRuntimeMonitorSelectedTaskRunId` and existing monitor detail fetch flow.
- Navigation: selecting a task in the right monitor opens the center detail view; the center view can return to the previous work surface.

## Implementation Steps

1. Split task detail rendering into a center view component.
2. Make `TaskMonitorDock` act as an index/list and call an optional open-detail callback after task selection.
3. Let `WorkbenchShell` switch its center content between normal workspace content and monitor detail content.
4. Add low-noise center monitor styles, with explicit empty/loading/error states.
5. Build and verify with Edge that right-side detail is gone and center detail appears.

