# Command workspace implementation

## Shared workspace, separate input destinations

`CommandWorkspace` owns the bottom splitter and composer. It reparents the
existing command-history widget rather than copying its contents. The
original command input retains completion, history navigation, and prompt
handling. The assistant's existing text input occupies the other composer
page. Switching pages preserves each field's draft.

Pane visibility is independent of input routing. Assistant and
Script Editor menu entries reveal their respective panes; only the explicit mode
controls select where composer input goes. Model/layout tabs stay above the
splitter, and pane proportions and visibility are stored with workspace
settings.

## Model providers and application operations

The assistant's `Agent` retains its provider-neutral text/tool/result
conversation. `AnthropicClient` uses the Anthropic protocol; `LocalClient`
translates between that internal representation and OpenAI-compatible Chat
Completions. HTTP runs on a worker, and geometry operations run on Qt's main
thread through `SerpApi`.

Local discovery prefers LM Studio's `/api/v1/models` capability metadata,
with `/v1/models` as a fallback. Unknown models are treated conservatively
for vision. Discovery is asynchronous, stale endpoint results are ignored,
and changing endpoints invalidates previously discovered capabilities.

Tool calls are assembled and validated before dispatch. Results retain
their call IDs, including image-tool results. Images are supplied as user
image parts in the local protocol. A failed later request retains completed
operations in the transcript. Cancellation suppresses queued operations;
starting a new chat clears the old transcript after cancellation finishes.

`SerpApi.external_operation` is the shared boundary for source attribution
and protecting pending CAD prompts. Read-only inspection remains available
while a command is waiting for user input. Conflicting mutations report an
error without canceling or replacing that command.

## Python drafts and staged geometry

`ScriptEditor` manages source files and drafts. `script_runtime` creates a
working document for a worker, with `doc`, `geo` and the selected inputs in
scope. The returned preview is separate from the live scene and from the
command processor's transient preview. Model viewports draw its additions
and changes in green and removals in red.

Keep checks the live document against the state captured at Run and refuses
to overwrite newer work or interleave with an unfinished CAD command. A
successful Keep makes one history checkpoint and applies the staged scene.
Scene snapshots include document units. Exceptions, Discard and cancellation
leave the live document untouched; external Python side effects are outside
this document transaction.

Generated outputs carry ownership in the drawing's history records. Native
loading remaps those records to loaded object IDs. Saving a draft updates
its ownership consistently in live, pending-preview and undo/redo states,
so a later rerun replaces its earlier outputs. Open drafts, paths and
identities are retained in settings after normal close.

`prepare_script(source, title)` opens a new draft without executing it. Its
tool description supplies the scripting globals and a small API example.
The assistant's completion handler preserves focus if the user has moved
into the script editor or viewport.

## Verification record

The implementation used separate test-writing, implementation, and review
phases for each feature. Existing unrelated edits were preserved.

### Workspace

- RED: nine failures for missing workspace and explicit-composer behavior.
- GREEN: `ui/command_workspace.py`, `app.py`, `ai/panel.py`, and
  `ui/command_line.py`; nine new tests passed.
- Review: no production cleanup needed. Existing command-area sizing tests
  now resize the workspace container and preserve their original thresholds.
- Regression result: 90 passed.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_the_bottom_workspace_keeps_input_explicit.py
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_ai.py tests/test_window_persistence.py tests/test_command_completion.py tests/test_space_acts_as_enter_in_the_command_line.py tests/test_layout_tabs.py tests/test_the_command_area_can_be_given_more_room.py tests/test_copying_the_command_history.py
```

### Local assistant

- RED: nine missing-provider failures and one pending-command overwrite.
- GREEN: `ai/local_client.py`, `ai/agent.py`, `ai/panel.py`,
  `ui/settings_dialog.py`, and `api.py`; ten new tests passed.
- Review: added seven regressions for discovery lifetime, stale metadata,
  retained tool results, empty responses, command errors, and chat reset.
- Final focused result: 41 passed.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_local_models_can_work_on_the_scene.py --tb=short
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_local_ai_review_edges.py tests/test_local_models_can_work_on_the_scene.py tests/test_ai.py tests/test_the_bottom_workspace_keeps_input_explicit.py --tb=short
```

Live verification used LM Studio at `127.0.0.1:1234` and
`qwen/qwen3.5-9b`. A controlled request created exactly one 40 × 30 × 20 box,
read it through `scene_info`, and returned a final answer. The measured
volume was 24,000 mm³. After command guidance was clarified, a plain-language
request also created the correct box; an empty model follow-up produced a
visible error and preserved the completed geometry. Automated provider
tests use mock HTTP and do not require a running model.

### Script editor

- RED: 15 failures for the missing multiline editor and Examples control.
- GREEN: new `script_runtime.py` and `ui/script_editor.py`, plus workspace,
  window cleanup, API/tool dispatch, viewport rendering, scene snapshots and
  native-file integration; all 15 acceptance tests passed.
- Review: six regression cases cover focus, draft recovery, Save ownership,
  undo/redo and drawing dirty state. Editor controls were compacted after
  native visual inspection.
- Final focused result: 55 passed.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --tb=short tests/test_scripts_are_editable_scene_previews.py
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --tb=short tests/test_script_workspace_review_edges.py tests/test_scripts_are_editable_scene_previews.py tests/test_scripting.py tests/test_ai.py tests/test_the_bottom_workspace_keeps_input_explicit.py tests/test_the_command_area_can_be_given_more_room.py
```

Native verification rendered a 12-rib preview while the live scene still
contained only the guide curve. Keep produced 12 valid solids, undo restored
the guide alone, redo restored the ribs, and rerunning with eight ribs
replaced the previous outputs while retaining guide selection. The documented
curved-guide example also ran directly against the geometry API.

### Viewport display settings

- RED: nine failures for the permanent dock and missing viewport-menu entry.
- GREEN: `app.py`, `ui/display_panel.py`, and a context-bound workspace
  layout timer; 35 focused tests passed without changes to the RED tests.
- Review: no refactoring needed. The dialog follows its originating viewport,
  refreshes when that viewport changes, and is destroyed safely with its
  owner. Close/reopen and target replacement were also checked directly.
- Regression result: 128 passed.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_display_panel.py tests/test_viewport_title_menu.py --tb=short
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_window_persistence.py tests/test_panel_width_on_resize.py tests/test_maximize_viewport.py tests/test_viewports.py tests/test_four_viewports_can_always_be_got_back.py tests/test_the_bottom_workspace_keeps_input_explicit.py tests/test_the_command_area_can_be_given_more_room.py tests/test_a_layout_is_a_workspace.py tests/test_layout_tabs.py tests/test_the_new_layout_button.py --tb=short
```

### External MCP agents

- RED: 11 failures for missing history attribution, overwritten CAD prompts,
  and the absent `serp_prepare_script` tool.
- GREEN: `rpc.py` wraps the actual Qt-thread invocation in the shared API
  operation boundary; `mcp_server/server.py` registers the script handoff.
  All 16 focused tests passed without changes to the corrected RED tests.
- Review: no refactoring needed. The bridge delegates to the existing API
  without duplicating draft handling or command protection.
- AI/local-model/script regression result: 53 passed.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_mcp_operations_share_the_workspace.py tests/test_mcp_server.py --tb=short
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_ai.py tests/test_local_models_can_work_on_the_scene.py tests/test_local_ai_review_edges.py tests/test_scripts_are_editable_scene_previews.py tests/test_script_workspace_review_edges.py --tb=short
```

The broader regression run exposed an existing startup test that assumed
no OpenGL context remained current after earlier viewport tests. The same
startup assertion now runs in a fresh subprocess. The application probe
itself is unchanged; viewport and startup regressions passed together.

### Closing Python drafts

- RED: 12 failures for absent tab-close controls.
- GREEN: `ui/script_editor.py` adds close controls, targeted saves,
  Save/Discard/Cancel prompts, active-run/preview protection, and a blank
  replacement after the last tab closes. All 12 acceptance tests passed.
- Independent review: no refactoring needed. Noncurrent-tab saves retain
  the intended target across modal dialogs; widget deletion is deferred,
  and recovery only serializes surviving drafts.
- Script/workspace regression result: 40 passed.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_script_tabs_can_be_closed_without_losing_work.py --tb=short
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_script_workspace_review_edges.py tests/test_scripts_are_editable_scene_previews.py tests/test_scripting.py tests/test_the_bottom_workspace_keeps_input_explicit.py tests/test_the_command_area_can_be_given_more_room.py --tb=short
```

### Final regression run

The complete suite passed: **2,984 tests**, with 103 existing Qt deprecation
warnings, in 117.61 seconds. The process exited successfully. The repository
graph was refreshed with `rtk graft build` and `git diff --check` was clean.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --tb=short
```

### Installed application and documentation

The AppImage build passed its packaged import check and refreshed
`/home/chisomo-banzi/Applications/Serpentine3D.AppImage`. Its self-test passed
Qt startup, STEP export, and the expected filleted-box volume of 975.6 mm³.

A separate native run used that installed AppImage with an isolated profile.
Seventeen imported modules came from its mounted package and matched the
checkout by SHA-256. The run checked viewport-menu Display settings, the MCP
script tool, closable script tabs, unexecuted draft handoff, preview isolation,
and Keep/Undo/Redo. The screenshot in the workspace guide comes from this
packaged run. The user's existing application window and profile were not used.

```bash
rtk packaging/appimage/build-appimage.sh
rtk proxy /home/chisomo-banzi/Applications/Serpentine3D.AppImage --selftest
rtk proxy uvx --from mkdocs-material mkdocs build --strict --site-dir /tmp/serpentine-workspace-docs-build
```

## Workspace density pass

The input destination buttons, active field, and submission button now share
one row. The ordinary Command prompt label is omitted when the selected mode
already identifies it; actual command prompts remain visible. Static input
instructions and draft reminders are available in tooltips.

Script file tabs share their row with Examples, Run, and the script actions
menu. Stop appears while a script runs; Keep and Discard appear for a pending
preview. They remain discoverable in the actions menu. The assistant's model,
New chat, and Settings share one header, and provider setup lives in Settings.
The redundant pane titles and assistant input-hint row were removed, and
default workspace heights were reduced to give more space to the viewport.

A native comparison used the same 1600-wide window and 360-pixel workspace,
with unchanged editor text size. The command composer fell from 102 to 36
logical pixels. An empty script editor gained space from five visible lines
to fifteen. Command and AI modes, an active Line prompt, and 1280-wide layout
were inspected. Native script runs also checked preview buttons fit inside
both wide and narrow panes, and verified Keep/Undo/Redo.

The layout pass passed 247 command, workspace, provider, MCP, script and
layout checks. Following the final Qt corner-widget reflow adjustment, the
64 focused interaction checks passed again. The existing AI setup test now
checks setup dismissal rather than a hint row which no longer occupies
the assistant pane.

The refreshed installed AppImage passed its self-test and native workspace
probe. All 17 imported module hashes matched the checkout. The packaged
composer measured 36 pixels, and preview actions, Keep/Undo/Redo and the
viewport display entry worked in the rendered window. The workspace guide's
screenshot was refreshed from this installed build.

```bash
rtk proxy env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_the_bottom_workspace_keeps_input_explicit.py tests/test_scripts_are_editable_scene_previews.py tests/test_script_tabs_can_be_closed_without_losing_work.py tests/test_script_workspace_review_edges.py tests/test_ai.py tests/test_the_command_area_can_be_given_more_room.py --tb=short
```
