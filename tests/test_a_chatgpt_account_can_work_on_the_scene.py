"""The Assistant connects a ChatGPT account through Codex's public app-server.

Qt, configuration, the agent, scene, and command history are real. A temporary
executable on PATH replaces only the external Codex process. Its JSONL messages
follow the installed 0.153.4 public experimental schema, including dynamic tools.
No test needs an installed Codex, credentials, a browser, or a cloud request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import webbrowser

import httpx
import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QWidget

from serpentine3d.app import MainWindow


MODEL = "gpt-scene-test"
MODEL_LABEL = "Scene Test Model"
AUTH_URL = "https://auth.openai.com/oauth/authorize?state=serpentine-test"
ACCOUNT = {"type": "chatgpt", "email": "designer@example.test", "planType": "plus"}
BOX = {"command": "Box", "inputs": ["0,0,0", "4,5,0", "6"]}


# Kept separate from the application boundary: this runs in a real child
# process and receives stdin, emits stdout, and exits on EOF/termination.
FAKE_CODEX = r'''
import copy, json, os, pathlib, queue, signal, sys, threading, time, tomllib

root = pathlib.Path(os.environ["SERPENTINE_TEST_CODEX_DIR"])
pid = os.getpid()
events = set(root.glob("event-*.json"))
inbox = queue.Queue()
initialized = False
thread_id = "01970000-0000-7000-8000-000000000001"
turn_id = None
pending_tool = None
pending_login = None
login_count = 0
turn_count = 0
tool_name = None

def merge_config(target, values):
    # App-server thread overrides may use dotted keys or nested objects.
    for key, value in values.items():
        parts = key.split(".")
        cursor = target
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        if isinstance(value, dict):
            merge_config(cursor.setdefault(parts[-1], {}), value)
        else:
            cursor[parts[-1]] = value

process_config = {}
args = iter(sys.argv[1:])
for arg in args:
    if arg in ("-c", "--config"):
        merge_config(process_config, tomllib.loads(next(args)))
    elif arg.startswith("--config="):
        merge_config(process_config, tomllib.loads(arg.split("=", 1)[1]))
    elif arg in ("--disable", "--enable"):
        merge_config(process_config, {"features." + next(args): arg == "--enable"})

inherited_config = {"mcp_servers": {"inherited_work_tools": {
    "command": "unrelated-work-tools", "enabled": True}}}
merge_config(inherited_config, process_config)

def log(kind, **data):
    with (root / "wire.jsonl").open("a") as out:
        out.write(json.dumps(dict(kind=kind, pid=pid, **data)) + "\n")

def send(message):
    log("server", message=message)
    print(json.dumps(message), flush=True)

def reply(request, result):
    send({"id": request["id"], "result": result})

def notify(method, params):
    send({"method": method, "params": params})

def turn(status):
    return {"id": turn_id, "items": [], "status": status, "error": None}

def delta(text):
    notify("item/agentMessage/delta", {"threadId": thread_id,
        "turnId": turn_id, "itemId": "answer-" + turn_id, "delta": text})

def issue_tool():
    global pending_tool
    pending_tool = "scene-tool-" + turn_id
    send({"id": pending_tool, "method": "item/tool/call", "params": {
        "threadId": thread_id, "turnId": turn_id, "callId": "call-" + turn_id,
        "tool": tool_name or "serp_run_command", "arguments": {
            "command": "Box", "inputs": ["0,0,0", "4,5,0", "6"]}}})

def read_stdin():
    for line in sys.stdin:
        inbox.put(line)
    inbox.put(None)

def end(signum, frame):
    raise SystemExit(0)

signal.signal(signal.SIGTERM, end)
log("start", argv=sys.argv[1:])
if "--version" in sys.argv:
    print("codex-cli 0.153.4")
    sys.exit(0)
if "app-server" not in sys.argv:
    log("protocol_error", error="The supported account boundary is codex app-server")
    sys.exit(2)
threading.Thread(target=read_stdin, daemon=True).start()
try:
    while True:
        for path in sorted(root.glob("event-*.json")):
            if path in events:
                continue
            events.add(path)
            event = json.loads(path.read_text())
            if event.get("action") == "release_tool":
                issue_tool()
            else:
                params = event.get("params", {})
                if event.get("method") == "account/login/completed" and params.get("success"):
                    (root / "account.json").write_text(json.dumps({"type": "chatgpt",
                        "email": "designer@example.test", "planType": "plus"}))
                send(event)
        try:
            line = inbox.get(timeout=0.01)
        except queue.Empty:
            continue
        if line is None:
            break
        request = json.loads(line)
        log("client", message=request)
        method = request.get("method")
        params = request.get("params") or {}
        if method is None:
            if request.get("id") == pending_tool:
                result = request.get("result", {})
                if result.get("success"):
                    delta("Created your 4 by 5 by 6 box.")
                else:
                    delta("Finish the active command first.")
                notify("turn/completed", {"threadId": thread_id, "turn": turn("completed")})
                pending_tool = None
            continue
        if method == "initialize":
            assert params.get("clientInfo", {}).get("name"), "initialize needs clientInfo"
            assert params.get("capabilities", {}).get("experimentalApi"), "Dynamic tools require experimentalApi"
            reply(request, {"userAgent": "codex-test/0.153.4", "platformFamily": "unix",
                            "platformOs": "linux"})
        elif method == "initialized":
            initialized = True
        else:
            assert initialized, "Send initialized before account or conversation requests"
            if method == "account/read":
                account = json.loads((root / "account.json").read_text())
                reply(request, {"account": account, "requiresOpenaiAuth": True})
            elif method == "config/read":
                assert "includeLayers" not in params or isinstance(params["includeLayers"], bool)
                reply(request, {"config": inherited_config, "origins": {},
                                "layers": [] if params.get("includeLayers") else None})
            elif method == "model/list":
                reply(request, {"data": [{"id": "gpt-scene-test", "model": "gpt-scene-test",
                    "displayName": "Scene Test Model", "description": "Fake available account model",
                    "hidden": False, "isDefault": True, "inputModalities": ["text"],
                    "defaultReasoningEffort": "medium", "supportedReasoningEfforts": []}],
                    "nextCursor": None})
            elif method == "account/login/start":
                assert params.get("type") == "chatgpt", "Use the managed browser flow"
                login_count += 1
                pending_login = "login-" + str(pid) + "-" + str(login_count)
                reply(request, {"type": "chatgpt", "loginId": pending_login,
                    "authUrl": "https://auth.openai.com/oauth/authorize?state=serpentine-test"})
            elif method == "account/login/cancel":
                assert params.get("loginId") == pending_login
                reply(request, {"status": "canceled"})
                pending_login = None
            elif method == "account/logout":
                log("protocol_error", error="Disconnect must not log out the shared Codex account")
                (root / "account.json").write_text("null")
                reply(request, {})
            elif method == "thread/start":
                effective_config = copy.deepcopy(inherited_config)
                merge_config(effective_config, params.get("config") or {})
                assert effective_config["mcp_servers"]["inherited_work_tools"].get("enabled") is False, \
                    "Scene conversations must disable inherited MCP servers"
                for feature in ("shell_tool", "apps", "plugins"):
                    assert process_config.get("features", {}).get(feature) is False, \
                        "The scene app-server process must disable " + feature
                    assert effective_config.get("features", {}).get(feature) is False, \
                        "Scene conversations must keep " + feature + " disabled"
                # Verified against the real app-server: chat still streams with
                # this host disabled, but no dynamic scene tool can execute.
                assert effective_config.get("features", {}).get("code_mode_host") is True, \
                    "Codex's dynamic tool host must remain available for scene operations"
                specs = params.get("dynamicTools", [])
                matches = [spec for spec in specs if spec.get("type") == "function"
                           and spec.get("name", "").endswith("run_command")]
                assert matches, "Advertise the real Serpentine run_command dynamic tool"
                tool_name = matches[0]["name"]
                assert matches[0].get("inputSchema") and matches[0].get("description")
                assert params.get("model") == "gpt-scene-test", "Use the user's discovered model"
                cwd = params.get("cwd") or os.getcwd()
                reply(request, {"thread": {"id": thread_id, "sessionId": thread_id,
                    "preview": "", "ephemeral": True, "modelProvider": "openai",
                    "createdAt": 1, "updatedAt": 1, "status": {"type": "idle"},
                    "cwd": cwd, "cliVersion": "0.153.4", "source": "appServer",
                    "projectId": None, "turns": []}, "model": params["model"],
                    "modelProvider": "openai", "cwd": cwd, "approvalPolicy": "never",
                    "approvalsReviewer": "user", "sandbox": {"type": "readOnly"}})
            elif method == "turn/start":
                assert params.get("threadId") == thread_id
                assert all(item.get("type") == "text" for item in params.get("input", []))
                turn_count += 1
                turn_id = "01970000-0000-7000-8000-" + str(turn_count).zfill(12)
                reply(request, {"turn": turn("inProgress")})
                notify("turn/started", {"threadId": thread_id, "turn": turn("inProgress")})
                prompt = " ".join(item.get("text", "") for item in params["input"])
                if "still there" in prompt:
                    delta("Ready for your next request.")
                    notify("turn/completed", {"threadId": thread_id, "turn": turn("completed")})
                else:
                    delta("I will make the box. ")
                    # Tests release the tool after observing this streamed prefix.
            elif method == "turn/interrupt":
                assert params.get("threadId") == thread_id and params.get("turnId") == turn_id
                reply(request, {})
                issue_tool()  # A tool already in transit must not mutate after Stop.
                notify("turn/completed", {"threadId": thread_id, "turn": turn("interrupted")})
            else:
                log("protocol_error", error="Unexpected method: " + str(method))
                send({"id": request.get("id"), "error": {"code": -32601,
                    "message": "Unexpected test app-server method: " + str(method)}})
except BaseException as exc:
    if not isinstance(exc, SystemExit):
        log("protocol_error", error=repr(exc))
        raise
finally:
    log("exit")
'''


class CodexProcess:
    def __init__(self, root):
        self.root = root
        self.browser_urls = []
        self.sequence = 0
        self.account(ACCOUNT)

    def account(self, value):
        (self.root / "account.json").write_text(json.dumps(value))

    def log(self):
        path = self.root / "wire.jsonl"
        if not path.exists():
            return []
        lines = path.read_text().splitlines()
        # Appends from the external process may be in progress while Qt pumps.
        return [json.loads(line) for line in lines if line.endswith("}")]

    def requests(self, method):
        return [item["message"] for item in self.log()
                if item["kind"] == "client" and item["message"].get("method") == method]

    def responses(self):
        return [item["message"] for item in self.log()
                if item["kind"] == "client" and "method" not in item["message"]]

    def emit(self, message):
        self.sequence += 1
        temporary = self.root / "next-event.tmp"
        temporary.write_text(json.dumps(message))
        temporary.replace(self.root / f"event-{self.sequence:04d}.json")

    def complete_login(self, success=True, error=None, login_id=None):
        replies = [item["message"]["result"] for item in self.log()
                   if item["kind"] == "server" and "loginId" in item["message"].get("result", {})]
        assert replies, "Codex must start a browser login before it can complete"
        self.emit({"method": "account/login/completed", "params": {
            "loginId": login_id or replies[-1]["loginId"], "success": success, "error": error}})

    def alive(self):
        pids = {item["pid"] for item in self.log() if item["kind"] == "start"
                and "app-server" in item["argv"]}
        if sys.platform == "win32":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            alive = []
            for pid in pids:
                handle = kernel.OpenProcess(0x100000, False, pid)
                if handle:
                    try:
                        if kernel.WaitForSingleObject(handle, 0) == 258:
                            alive.append(pid)
                    finally:
                        kernel.CloseHandle(handle)
            return alive
        return [pid for pid in pids if (Path(f"/proc/{pid}/stat").exists()
                and Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z")]


@pytest.fixture
def codex(monkeypatch, tmp_path):
    fake = CodexProcess(tmp_path)
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    binary = binary_dir / ("codex.cmd" if sys.platform == "win32" else "codex")
    fake.binary = binary
    if sys.platform == "win32":
        script = tmp_path / "fake_codex.py"
        script.write_text(FAKE_CODEX, encoding="utf-8")
        binary.write_text(f'@echo off\n"{sys.executable}" "{script}" %*\n')
    else:
        binary.write_text(f"#!{sys.executable}\n" + FAKE_CODEX)
    binary.chmod(0o755)
    # Isolate both shell and desktop installation discovery from real accounts.
    monkeypatch.setenv("PATH", str(binary_dir))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData/Roaming"))
    monkeypatch.setenv("SERPENTINE_TEST_CODEX_DIR", str(tmp_path))

    def browser(url, *args, **kwargs):
        fake.browser_urls.append(url.toString() if hasattr(url, "toString") else str(url))
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", browser)
    monkeypatch.setattr(webbrowser, "open", browser)
    monkeypatch.setattr(webbrowser, "open_new_tab", browser)

    def no_network(*args, **kwargs):
        raise AssertionError("ChatGPT account tests must use the fake Codex process, not HTTP")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    yield fake
    for pid in fake.alive():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.fixture
def windows(monkeypatch, tmp_path, codex):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    opened = []

    def create():
        window = MainWindow()
        opened.append(window)
        window.resize(1400, 900)
        _lay_out(window)
        return window

    yield create
    for window in opened:
        panel = window.command_workspace.assistant
        if panel is not None and panel.agent is not None and panel.agent.busy:
            panel.agent.stop()
            _wait(lambda: not panel.agent.busy, "Assistant must stop at teardown")
        window.processor.cancel()
        window.mark_saved()
        window.close()
    QApplication.processEvents()


def _wait(predicate, message, seconds=6):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    QApplication.processEvents()
    assert predicate(), message


def _lay_out(window):
    window.layout().activate()
    shelf = window._cmd_dock.widget()
    shelf.resize(1100, 360)
    for _ in range(2):
        for widget in [shelf, *shelf.findChildren(QWidget)]:
            if widget.layout() is not None:
                widget.layout().invalidate()
                widget.layout().activate()
    QApplication.processEvents()


def _description(widget):
    return " ".join((widget.text(), widget.accessibleName(), widget.toolTip()))


def _buttons(root, pattern):
    return [button for button in root.findChildren(QAbstractButton)
            if button.isVisibleTo(root) and re.search(pattern, _description(button), re.I)]


def _click(root, pattern):
    matches = _buttons(root, pattern)
    exact = [button for button in matches if re.fullmatch(pattern, button.text().strip(), re.I)]
    matches = exact or matches
    assert len(matches) == 1, f"Expected one visible {pattern!r} action; found {len(matches)}"
    assert matches[0].isEnabled(), f"The {pattern!r} action must be enabled"
    matches[0].click()


def _text(panel):
    return "\n".join(label.text() for label in panel.findChildren(QLabel)
                     if label.isVisibleTo(panel))


def _choices(panel, pattern):
    result = [(button, None) for button in _buttons(panel, pattern) if button.isEnabled()]
    for combo in panel.findChildren(QComboBox):
        if combo.isVisibleTo(panel) and combo.isEnabled():
            result.extend((combo, index) for index in range(combo.count())
                          if re.search(pattern, combo.itemText(index), re.I))
    return result


def _choose_chatgpt(window):
    panel = window.show_ai_panel()
    _lay_out(window)
    choices = _choices(panel, r"chatgpt")
    if not choices:
        categories = _choices(panel, r"\bcloud\b|\baccounts?\b")
        assert categories, "The Assistant must offer cloud account connections"
        control, index = categories[0]
        control.click() if index is None else control.setCurrentIndex(index)
        _lay_out(window)
        choices = _choices(panel, r"chatgpt")
    assert choices, "The Assistant cloud choices must offer ChatGPT account sign-in through Codex"
    control, index = choices[0]
    control.click() if index is None else control.setCurrentIndex(index)
    _lay_out(window)
    return panel


def _models(panel):
    return next((combo for combo in panel.findChildren(QComboBox)
                 if combo.isVisibleTo(panel) and any(
                     combo.itemData(i) == MODEL or MODEL_LABEL in combo.itemText(i)
                     for i in range(combo.count()))), None)


def _not_connected(window, panel, codex):
    assert not panel.is_ready(), "Setup, cancellation, and failure must not claim a connection"
    assert not codex.requests("turn/start"), "Setup must never send an implicit prompt"
    assert not window.scene.all()


def _discover_existing(window, panel, codex):
    # Account discovery may start on choosing the provider, or have its own
    # user-facing action. Both lead to the same observable review step.
    actions = _buttons(panel, r"reuse|use existing|check.*account|refresh|discover")
    enabled = [button for button in actions if button.isEnabled()]
    if enabled:
        enabled[0].click()
    _wait(lambda: _models(panel) is not None,
          "An existing ChatGPT account must expose the models returned by Codex model/list")
    assert codex.requests("account/read") and codex.requests("model/list")
    assert not codex.requests("account/login/start") and not codex.browser_urls, \
        "Reusing an existing account must not start a new browser login"
    _not_connected(window, panel, codex)


def _connect(window, panel, codex):
    models = _models(panel)
    assert models is not None, "Choose from account models before connecting"
    for index in range(models.count()):
        if models.itemData(index) == MODEL or MODEL_LABEL in models.itemText(index):
            models.setCurrentIndex(index)
            break
    _click(panel, r"\bconnect\b")
    _wait(panel.is_ready, "Explicit Connect must enable the Assistant composer")
    _lay_out(window)
    assert "chatgpt" in panel.recipient.text().lower()
    assert MODEL_LABEL.lower() in panel.recipient.text().lower() or MODEL in panel.recipient.text()
    assert not codex.requests("turn/start"), "Connecting is not consent to send a prompt"


def _existing_connection(windows, codex):
    window = windows()
    panel = _choose_chatgpt(window)
    _discover_existing(window, panel, codex)
    _connect(window, panel, codex)
    return window, panel


def _send(window, panel, prompt):
    _click(window._cmd_dock.widget(), r"Ask AI")
    _lay_out(window)
    panel.input.setPlainText(prompt)
    submit = window.command_workspace.submit_button
    assert submit.isEnabled() and re.search(r"send", submit.text(), re.I)
    submit.click()


def _assert_no_credentials_or_logout(window, codex):
    assert not codex.requests("account/logout"), "Serpentine must preserve the shared Codex login"
    assert json.loads((codex.root / "account.json").read_text()) == ACCOUNT
    config = json.loads((codex.root / "settings.json").read_text())
    ai = json.dumps(config.get("ai", {})).lower()
    assert not any(name in ai for name in ("access_token", "refresh_token", "id_token",
                                            "accesstoken", "refreshtoken", "chatgptauthtokens"))
    errors = [item["error"] for item in codex.log() if item["kind"] == "protocol_error"]
    assert not errors, f"App-server protocol errors: {errors}"


def test_chatgpt_choice_explains_the_missing_codex_prerequisite(windows, codex):
    codex.binary.unlink()
    window = windows()
    panel = _choose_chatgpt(window)
    _wait(lambda: re.search(r"codex", _text(panel), re.I)
          and re.search(r"install|not found|not installed|requires", _text(panel), re.I),
          "When Codex is absent, show its prerequisite and an actionable installation/help path")
    visible = _text(panel) + " " + " ".join(_description(b) for b in _buttons(panel, r".*"))
    assert re.search(r"https?://|npm\s+install|install codex|setup guide|help", visible, re.I)
    _not_connected(window, panel, codex)
    assert not codex.browser_urls, "Choosing a provider must not open a browser automatically"


def test_desktop_launch_finds_an_existing_nvm_install(windows, codex, monkeypatch):
    install = codex.root / ".nvm/versions/node/v22.22.2/bin"
    install.mkdir(parents=True)
    codex.binary.rename(install / codex.binary.name)
    monkeypatch.setenv("PATH", str(codex.root / "empty-path"))
    window, panel = _existing_connection(windows, codex)
    assert panel.is_ready()
    assert codex.requests("account/read")
    _assert_no_credentials_or_logout(window, codex)


def test_existing_account_is_reviewed_explicitly_connected_and_reused_after_reopen(windows, codex):
    window, panel = _existing_connection(windows, codex)
    assert codex.alive(), "The connected account owns a Codex app-server subprocess"
    from serpentine3d.ui.settings_dialog import SettingsDialog
    before = json.loads((codex.root / "settings.json").read_text()).get("ai", {})
    settings = SettingsDialog(window)
    settings.close()
    after = json.loads((codex.root / "settings.json").read_text()).get("ai", {})
    assert after == before, "Opening Settings must preserve the selected ChatGPT account and model"
    window.mark_saved()
    window.close()
    _wait(lambda: not codex.alive(), "Closing the window must clean up its Codex subprocess")
    _assert_no_credentials_or_logout(window, codex)

    reopened = windows()
    again = reopened.show_ai_panel()
    _lay_out(reopened)
    _wait(again.is_ready, "The selected account and model must be reusable after reopening")
    assert "chatgpt" in again.recipient.text().lower()
    assert MODEL_LABEL.lower() in again.recipient.text().lower() or MODEL in again.recipient.text()
    assert not codex.requests("account/login/start") and not codex.requests("turn/start")


def test_browser_sign_in_stays_pending_until_the_matching_completion(windows, codex):
    codex.account(None)
    window = windows()
    panel = _choose_chatgpt(window)
    _wait(lambda: any(b.isEnabled() for b in _buttons(panel, r"sign in|log in")),
          "An unsigned account needs a visible Sign in action")
    assert not codex.browser_urls and not codex.requests("account/login/start")
    _click(panel, r"sign in|log in")
    _wait(lambda: bool(codex.browser_urls), "User Sign in must open the official auth URL")
    assert codex.browser_urls == [AUTH_URL]
    assert codex.requests("account/login/start")[-1]["params"]["type"] == "chatgpt"
    _not_connected(window, panel, codex)
    assert re.search(r"waiting|pending|browser|complete.*sign", _text(panel), re.I)
    assert _buttons(panel, r"cancel"), "A browser flow must remain cancellable"

    codex.complete_login(success=False, error="Unrelated login", login_id="some-other-login")
    QTest.qWait(50)
    _not_connected(window, panel, codex)
    assert "Unrelated login" not in _text(panel), "Ignore completion for another login attempt"
    codex.complete_login()
    _wait(lambda: _models(panel) is not None, "Successful login must discover the account models")
    _not_connected(window, panel, codex)
    _connect(window, panel, codex)
    _assert_no_credentials_or_logout(window, codex)


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_cancelled_or_failed_login_never_persists_a_connection_and_can_retry(windows, codex, outcome):
    codex.account(None)
    window = windows()
    panel = _choose_chatgpt(window)
    _wait(lambda: any(b.isEnabled() for b in _buttons(panel, r"sign in|log in")),
          "An unsigned account needs Sign in")
    _click(panel, r"sign in|log in")
    _wait(lambda: bool(codex.browser_urls), "The browser flow did not start")
    if outcome == "cancel":
        _click(panel, r"cancel")
        _wait(lambda: bool(codex.requests("account/login/cancel")), "Cancel must cancel this Codex login")
        codex.complete_login()  # A completion already in flight cannot connect Serpentine.
        QTest.qWait(50)
    else:
        codex.complete_login(success=False, error="Account sign-in declined by the test provider")
        _wait(lambda: "declined" in _text(panel).lower(), "Show the provider's login failure")
    _not_connected(window, panel, codex)
    _wait(lambda: any(b.isEnabled() for b in _buttons(panel, r"sign in|log in|retry")),
          "Cancelled or failed authentication must offer a visible retry")
    retry = [b for b in _buttons(panel, r"sign in|log in|retry") if b.isEnabled()][0]
    retry.click()
    _wait(lambda: len(codex.requests("account/login/start")) == 2,
          "Retry must start a fresh managed login attempt")
    codex.complete_login()
    _wait(lambda: _models(panel) is not None, "Retry must make authenticated models available")
    _connect(window, panel, codex)


def test_account_prompt_streams_and_executes_a_real_scene_tool_with_shared_history(windows, codex):
    window, panel = _existing_connection(windows, codex)
    _send(window, panel, "Make a 4 by 5 by 6 box")
    _wait(lambda: "I will make the box." in _text(panel),
          "Account text deltas must be visible before the turn completes")
    assert panel.agent.busy and not window.scene.all()
    codex.emit({"action": "release_tool"})
    _wait(lambda: not panel.agent.busy and bool(codex.responses()),
          "The account turn must complete its Serpentine dynamic-tool round trip")
    assert len(window.scene.all()) == 1 and window.scene.all()[0].kind == "solid"
    from serpentine3d.core import geometry
    low, high = geometry.bbox(window.scene.all()[0].shape)
    assert tuple(high[i] - low[i] for i in range(3)) == pytest.approx((4, 5, 6))
    result = next(message["result"] for message in codex.responses()
                  if str(message["id"]).startswith("scene-tool-"))
    assert result["success"] is True and result["contentItems"][0]["type"] == "inputText"
    assert "Created your 4 by 5 by 6 box." in _text(panel)
    history = window.command_line.echo_view.toPlainText()
    assert any(re.search(r"\b(ai|assistant)\b", line, re.I) and "box" in line.lower()
               for line in history.splitlines()), "Account tool work belongs in shared command history"
    assert "Unknown command" not in history and not window.processor.busy
    assert len(codex.requests("turn/start")) == 1, "A tool result continues the original Codex turn"
    _assert_no_credentials_or_logout(window, codex)


def test_account_tool_preserves_a_cad_prompt_started_while_the_model_was_thinking(windows, codex):
    window, panel = _existing_connection(windows, codex)
    _send(window, panel, "Make a box")
    _wait(lambda: "I will make the box." in _text(panel), "The account turn did not start")
    window.processor.run("line")
    window.processor.provide_text("1,2,3")
    request = window.processor.request
    points = list(window.processor.picked_points)
    codex.emit({"action": "release_tool"})
    _wait(lambda: not panel.agent.busy and bool(codex.responses()), "The protected tool must return a result")
    assert window.processor.busy and window.processor.request is request
    assert window.processor.picked_points == points and not window.scene.all()
    result = next(message["result"] for message in codex.responses()
                  if str(message["id"]).startswith("scene-tool-"))
    assert result["success"] is False
    assert re.search(r"finish|pending|busy|active", json.dumps(result), re.I)
    window.processor.provide_text("5,2,3")
    assert len(window.scene.all()) == 1, "The original CAD line must remain finishable"


def test_stop_interrupts_the_account_turn_and_rejects_late_scene_calls(windows, codex):
    window, panel = _existing_connection(windows, codex)
    _send(window, panel, "Make a box slowly")
    _wait(lambda: "I will make the box." in _text(panel), "The account turn did not start")
    submit = window.command_workspace.submit_button
    assert submit.isEnabled() and re.search(r"stop", submit.text(), re.I)
    submit.click()
    _wait(lambda: not panel.agent.busy and bool(codex.requests("turn/interrupt")),
          "Stop must interrupt the active Codex turn")
    QTest.qWait(50)
    assert not window.scene.all(), "A tool arriving after Stop must not mutate the scene"
    _send(window, panel, "are you still there")
    _wait(lambda: "Ready for your next request." in _text(panel) and not panel.agent.busy,
          "The connected account must remain usable after Stop")
    assert not window.scene.all()


def test_disconnect_closes_only_serpentines_process_and_preserves_the_codex_login(windows, codex):
    window, panel = _existing_connection(windows, codex)
    if not _buttons(panel, r"disconnect"):
        _click(panel, r"connection|change.*model|manage")
        _lay_out(window)
    _click(panel, r"disconnect")
    _wait(lambda: not codex.alive(), "Disconnect must close Serpentine's Codex subprocess")
    _not_connected(window, panel, codex)
    _assert_no_credentials_or_logout(window, codex)
    reopened = windows()
    again = reopened.show_ai_panel()
    _lay_out(reopened)
    assert not again.is_ready(), "Disconnect must persist in Serpentine without deleting the shared login"
