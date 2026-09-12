# Assistant connections

The Assistant pane owns connection setup and the conversation. The bottom
workspace owns the shared input and its explicit Command / Ask AI routing.
Opening a pane preserves both drafts and the current input mode. A model
must be selected and a connection saved before a prompt can be sent.

All providers use the same `Agent` tool-dispatch boundary. Model responses
stream on a worker; application operations execute on Qt's main thread and
appear in the shared command history. This preserves the existing rules for
pending CAD commands, Undo, and cancellation across providers.

Local model discovery is asynchronous. Results belong to the URL queried;
changing the URL invalidates them. Discovery previews the available models;
only Connect saves the selected connection. Errors remain in the setup pane
with a retry action.

ChatGPT account authentication uses the official Codex app-server protocol.
Codex owns token storage and refresh. Serpentine waits for a matching login
completion and a verified account before allowing connection. Its account
session is separate from the saved model choice, and disconnecting does not
sign the user out of Codex. Scene conversations use ephemeral threads with
Serpentine dynamic tools and process-local configuration.

## Verification

The connection behaviors follow separate RED → GREEN → REFACTOR cycles.
Tests use isolated application settings and fake provider transports; no
real credentials or browser access are required.

### First connection and local models

RED: four failures exposed the premature Anthropic recipient and missing
inline local setup. GREEN added the setup widget, asynchronous discovery,
explicit connection, readiness gating, and starter drafts. A fresh
REFACTOR review found no further cleanup necessary. Four focused tests and
61 relevant regression tests passed.

```bash
rtk env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_the_assistant_connects_before_the_first_prompt.py
```

### ChatGPT account

RED: nine failures exposed the missing ChatGPT connection choice. The
fixture runs an actual temporary executable that speaks the documented
Codex JSONL protocol. It covers login completion, cancellation and retry,
saved connections, scene tools, command history, pending CAD prompts,
Stop, Settings preservation, and process cleanup without logout.

GREEN added the app-server transport, account setup, and Agent adapter;
nine focused tests passed. A fresh REFACTOR review tightened cancellation,
process cleanup, and reconnection to the same model; 55 relevant tests passed.
Three additional temporary probes checked process loss during sign-in,
reconnection, and shutdown during a cancellation write failure.

A live check with Codex 0.153.4 and GPT-5.6-Luna reused the existing account
and created a 4 × 5 × 6 box in an isolated empty document. The operation
appeared in command history as `[AI] box 0,0,0 4,5,0 6`. This caught a
configuration issue absent from the original fake: `code_mode_host` must
remain enabled for dynamic tool dispatch even with `code_mode` disabled.
The corrected production code passed the live check in 9.17 seconds, and
the protocol fixture now guards against disabling that host.

```bash
rtk env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_a_chatgpt_account_can_work_on_the_scene.py
```

### Cloud API keys

RED: five failures exposed the missing OpenAI API-key provider. GREEN added
provider-specific credential/model settings and an OpenAI client that shares
the existing Chat Completions streaming and tool parser. The API endpoint
is fixed to OpenAI HTTPS, and keys are isolated from Anthropic and LM Studio.
Five focused tests passed, including a real scene operation through a fake
HTTP provider, environment precedence, redacted errors, and retry. A fresh
REFACTOR review found no additional cleanup necessary; the combined
connection and Settings suite passed 60 tests.

```bash
rtk env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_cloud_api_keys_can_work_on_the_scene.py
```

### External assistants and packaging

RED: four failures exposed the missing MCP setup action and the launcher's
failure to handle `--mcp` before Qt. GREEN added the compact setup dialog,
durable launch configuration, and headless routing. Four focused tests and
60 relevant regressions passed. A fresh REFACTOR review found no further
cleanup necessary. Tests launch the actual stdio server, initialize it,
and list its tools from a directory outside the repository.

```bash
rtk env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_external_assistants_can_connect_over_mcp.py
```

The final regression selection passed **120 tests**. A later copy-only
adjustment to local discovery feedback passed its four focused tests.
Desktop launch verification also found and fixed an installation-discovery
gap: Codex installed with NVM is found even when a desktop's PATH omits it.
An additional isolated NVM installation test passes; the account fixture
isolates both PATH and home-directory discovery from real accounts.

```bash
rtk env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_the_assistant_connects_before_the_first_prompt.py \
  tests/test_a_chatgpt_account_can_work_on_the_scene.py \
  tests/test_cloud_api_keys_can_work_on_the_scene.py \
  tests/test_external_assistants_can_connect_over_mcp.py \
  tests/test_ai.py tests/test_local_models_can_work_on_the_scene.py \
  tests/test_local_ai_review_edges.py \
  tests/test_the_bottom_workspace_keeps_input_explicit.py \
  tests/test_mcp_operations_share_the_workspace.py tests/test_mcp_server.py \
  tests/test_script_workspace_review_edges.py \
  tests/test_settings_view_transition.py tests/test_settings_chords.py \
  tests/test_spawn_safety.py tests/test_version_flag.py \
  tests/test_the_app_starts_on_an_egl_driver.py
```

## Installed application check — 2026-09-09

`rtk packaging/appimage/build-appimage.sh` rebuilt and refreshed
`~/Applications/Serpentine3D.AppImage`; the bundle import check passed.
The actual installed GUI matched SHA-256 hashes for 22 current modules.
An isolated profile verified the initial connection choices, all three
workspace panes at a 1280-pixel window width, a 407-pixel Assistant pane,
no horizontal scrolling, and the 36-pixel composer preserving Command mode.
Local discovery displayed actionable feedback for the stopped LM Studio
server. Account/model discovery succeeded with `PATH=/usr/bin:/bin`, using
the existing NVM installation; no login or inference was needed for that
installed check.

The MCP dialog produced the durable installed AppImage path and `--mcp`.
Running that copied command from `/tmp`, with both display variables unset,
completed initialization and listed all 15 tools. The installed AppImage's
`--selftest` also passed. Screenshots are saved in
`docs/assets/img/assistant-connections.png` and
`docs/assets/img/assistant-connections-workspace.png`.

API-key and local inference tests used fake provider transports. A live
ChatGPT geometry turn was verified separately against the source build as
described above. The user's LM Studio server was stopped during verification.
