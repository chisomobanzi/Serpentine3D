"""Codex app-server transport and the Assistant's scene-tool adapter.

Codex owns account authentication. Serpentine stores only the chosen model and
connection preference, and sends all scene operations through the normal Agent.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .client import AiError


_SCENE_FEATURES = {name: False for name in (
    "shell_tool", "unified_exec", "shell_snapshot", "apps", "plugins", "hooks",
    "plugin_hooks", "multi_agent", "code_mode",
    "js_repl", "browser_use", "computer_use", "image_generation", "view_image",
)}
# Codex dispatches dynamic scene tools through this host even when code mode
# itself is disabled. Disabling the host leaves working chat with no tools.
_SCENE_FEATURES["code_mode_host"] = True


def _codex_executable():
    executable = shutil.which("codex")
    if executable:
        return executable
    # Desktop launchers often lack the shell initialization that adds npm/NVM
    # to PATH. Check conventional per-user installs without running a shell.
    user_dir = Path.home()
    candidates = [user_dir / directory / "codex" for directory in (
        ".local/bin", ".npm-global/bin", ".volta/bin", "bin")]
    candidates.extend(path / "bin/codex" for path in sorted(
        (user_dir / ".nvm/versions/node").glob("*"),
        key=lambda path: tuple(int(part) for part in re.findall(r"\d+", path.name)),
        reverse=True))
    if os.name == "nt" and os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "npm/codex")
    for path in candidates:
        executable = shutil.which(str(path))
        if executable:
            return executable
    return None


class CodexServer:
    """One private stdio process; requests may come from UI and chat workers."""

    def __init__(self):
        self.process = None
        self.events = queue.Queue()
        self.account_events = queue.Queue()
        self._pending = {}
        self._lock = threading.Lock()
        self._serial = 0
        self._closed = False
        self.thread_config = {"features": dict(_SCENE_FEATURES),
                              "web_search": "disabled", "project_doc_max_bytes": 0}
        self._workspace = tempfile.TemporaryDirectory(prefix="serpentine-assistant-")

    @property
    def alive(self):
        return not self._closed and self.process is not None and self.process.poll() is None

    def start(self):
        executable = _codex_executable()
        if not executable:
            raise AiError("Codex is not installed. Install Codex, then retry.")
        if self._closed:
            raise AiError("The ChatGPT connection was closed.")
        command = [executable, "app-server"]
        for name, enabled in _SCENE_FEATURES.items():
            command.extend(["-c", f"features.{name}={str(enabled).lower()}"])
        command.extend(["-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0"])
        child_env = dict(os.environ)
        child_env["PATH"] = str(Path(executable).parent) + os.pathsep + child_env.get("PATH", "")
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            cwd=self._workspace.name, env=child_env,
        )
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.request("initialize", {
                "clientInfo": {"name": "serpentine3d", "title": "Serpentine3D", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            })
            self.send({"method": "initialized"})
            # Enumerate names through the public interface, keeping credentials
            # out of our configuration, diagnostics, and transcript.
            config = self.request("config/read", {"includeLayers": False}).get("config", {})
            self.thread_config["mcp_servers"] = {
                name: {"enabled": False} for name in config.get("mcp_servers", {})}
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "method" not in message:
                    with self._lock:
                        pending = self._pending.pop(message.get("id"), None)
                    if pending is not None:
                        pending.put(message)
                elif message["method"].startswith("account/"):
                    self.account_events.put(message)
                else:
                    self.events.put(message)
        finally:
            error = {"error": {"message": "Codex disconnected. Reconnect in the Assistant."}}
            with self._lock:
                waiting, self._pending = list(self._pending.values()), {}
            for pending in waiting:
                pending.put(error)
            self.events.put(error)

    def send(self, message):
        with self._lock:
            if not self.alive:
                raise AiError("Codex disconnected. Reconnect in the Assistant.")
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise AiError("Codex disconnected. Reconnect in the Assistant.") from exc

    def request(self, method, params, *, wait=True, timeout=30):
        pending = queue.Queue()
        with self._lock:
            self._serial += 1
            request_id = self._serial
            if wait:
                self._pending[request_id] = pending
        try:
            self.send({"id": request_id, "method": method, "params": params})
            if not wait:
                return None
            try:
                result = pending.get(timeout=timeout)
            except queue.Empty as exc:
                raise AiError("Codex did not respond. Retry the ChatGPT connection.") from exc
            if "error" in result:
                raise AiError(result["error"].get("message", "Codex request failed."))
            return result.get("result", {})
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def close(self):
        self._closed = True
        process = self.process
        if process is not None:
            # EOF lets command wrappers wait for their child before exiting.
            # Killing only cmd.exe leaves its Codex child holding the workspace.
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        taskkill = str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe")
                        subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    process.wait(timeout=1)
        self._workspace.cleanup()


class CodexClient:
    """Translate dynamic calls to Agent tool_use/tool_result without a new turn."""

    def __init__(self, server, model, *, vision=False):
        self.server = server
        self.model = model
        self.vision = vision
        self.thread_id = None
        self.turn_id = None
        self._pending_tools = {}
        self._interrupted = set()

    def close(self):
        self.interrupt()
        self.server.close()

    def interrupt(self):
        turn_id = self.turn_id
        if turn_id and turn_id not in self._interrupted and self.server.alive:
            self._interrupted.add(turn_id)
            try:
                self.server.request("turn/interrupt", {
                    "threadId": self.thread_id, "turnId": turn_id}, wait=False)
            except AiError:
                # A process exiting between alive and write is already stopped.
                pass

    @staticmethod
    def _content_items(content):
        if isinstance(content, str):
            return [{"type": "inputText", "text": content}]
        items = []
        for block in content or []:
            if block.get("type") == "image":
                source = block["source"]
                items.append({"type": "inputImage", "imageUrl":
                              f"data:{source['media_type']};base64,{source['data']}"})
            elif block.get("text"):
                items.append({"type": "inputText", "text": block["text"]})
        return items or [{"type": "inputText", "text": "Done."}]

    def _reject_tool(self, event, message="Operation stopped before execution."):
        if "id" in event:
            self.server.send({"id": event["id"], "result": {
                "contentItems": [{"type": "inputText", "text": message}], "success": False}})

    def stream_message(self, system, messages, tools, max_tokens=4096,
                       on_text=None, should_stop=None):
        should_stop = should_stop or (lambda: False)
        latest = messages[-1]["content"]
        continuation = isinstance(latest, list) and any(
            block.get("type") == "tool_result" for block in latest)
        if continuation:
            for block in latest:
                request_id = self._pending_tools.pop(block.get("tool_use_id"), None)
                if request_id is not None:
                    self.server.send({"id": request_id, "result": {
                        "contentItems": self._content_items(block.get("content", "")),
                        "success": not block.get("is_error", False) and not should_stop()}})
        else:
            if not self.thread_id or len(messages) == 1:
                specs = [{"type": "function", "name": "serp_" + tool["name"],
                          "description": tool["description"], "inputSchema": tool["input_schema"]}
                         for tool in tools if self.vision or tool["name"] != "screenshot"]
                started = self.server.request("thread/start", {
                    "model": self.model, "modelProvider": "openai", "ephemeral": True,
                    "cwd": self.server._workspace.name, "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "config": self.server.thread_config,
                    "baseInstructions": system + "\nUse only the serp_ tools for this scene. "
                    "Their names have a serp_ prefix. Do not use shell, files, apps or external tools.",
                    "dynamicTools": specs,
                })
                self.thread_id = started["thread"]["id"]
            started = self.server.request("turn/start", {
                "threadId": self.thread_id, "input": [{"type": "text", "text": str(latest)}]})
            self.turn_id = started["turn"]["id"]
        text = []
        deadline = time.monotonic() + 180
        while True:
            if should_stop():
                self.interrupt()
                return {"content": [], "stop_reason": "aborted"}
            try:
                event = self.server.events.get(timeout=.05)
            except queue.Empty:
                if not self.server.alive:
                    raise AiError("Codex disconnected. Reconnect in the Assistant.")
                if time.monotonic() > deadline:
                    self.interrupt()
                    raise AiError("The ChatGPT response timed out. Please try again.")
                continue
            deadline = time.monotonic() + 180
            method, params = event.get("method"), event.get("params", {})
            if "error" in event and method is None:
                raise AiError(event["error"]["message"])
            event_turn = params.get("turnId") or params.get("turn", {}).get("id")
            current = (params.get("threadId") == self.thread_id
                       and event_turn == self.turn_id and event_turn not in self._interrupted)
            if method == "item/tool/call":
                if not current or should_stop():
                    self._reject_tool(event)
                    continue
                name = params.get("tool", "")
                if not name.startswith("serp_") or name[5:] not in {t["name"] for t in tools}:
                    self._reject_tool(event, "This tool is not available in Serpentine.")
                    continue
                args = params.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                call_id = params["callId"]
                self._pending_tools[call_id] = event["id"]
                content = ([{"type": "text", "text": "".join(text)}] if text else [])
                content.append({"type": "tool_use", "id": call_id, "name": name[5:], "input": args})
                return {"content": content, "stop_reason": "tool_use"}
            if "id" in event and method:
                self.server.send({"id": event["id"], "error": {
                    "code": -32601, "message": "Only Serpentine scene tools are available."}})
            if not current:
                continue
            if method == "item/agentMessage/delta":
                delta = params.get("delta", "")
                text.append(delta)
                if on_text:
                    on_text(delta)
            elif method == "turn/completed":
                self.turn_id = None
                turn = params.get("turn", {})
                if turn.get("error"):
                    raise AiError(turn["error"].get("message", "ChatGPT could not complete the request."))
                return {"content": [{"type": "text", "text": "".join(text)}],
                        "stop_reason": "end_turn"}
            elif method == "error" and not params.get("willRetry", False):
                raise AiError(params.get("error", {}).get("message", "ChatGPT request failed."))
