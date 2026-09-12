"""The assistant's agentic loop.

Runs on a worker thread (network I/O must not block the UI); every tool
call is marshalled onto the Qt main thread with a blocking queued signal
— the same pattern the RPC bridge uses. Signals stream progress to the
chat panel.
"""

from __future__ import annotations

import base64
import threading
import traceback

from PySide6.QtCore import QObject, Qt, Signal

from ..api import ApiError
from . import tools as T
from .client import AiError

MAX_STEPS_DEFAULT = 30

_SYSTEM = """\
You are the modelling assistant inside Serpentine3D, an open-source NURBS \
3D modeller. You build and edit real BREP geometry in the user's live \
scene by calling tools.

World conventions: Z is up, the construction plane is world XY, units are \
generic model units (treat them as the user's working units — mm, cm, m — \
and keep proportions consistent). Objects are referenced by name.

How to work:
- If the request refers to existing geometry and you aren't certain what \
exists, call scene_info first.
- Prefer the structured tools (create_curve, create_surface, boolean, \
transform). For everything else — primitives like box/sphere/cylinder, \
fillets, arrays, osnaps, display modes — use run_command with the command \
reference below.
- Build compound shapes from profiles: draw curves, then extrude/revolve/\
loft/sweep, then boolean.
- After building something non-trivial, call screenshot and LOOK at it. \
If it is wrong, fix it before answering. Set an informative view first \
(viewport tool: perspective + zoom_extents is a good default).
- Keep object names meaningful (name= parameters) so later edits are easy.
- Everything you do is undoable; when the user asks to remove your work, \
prefer undo.
- Be concise in prose. The user watches geometry appear live — narrate \
briefly, don't write essays.

Command reference (run_command): every command speaks its prompts in \
order; supply inputs as strings. Points are "x,y,z". Selection prompts \
take object names, "all", or "" to end selection.
Box takes THREE inputs: first base corner, opposite base corner, then \
height. For a 40 by 30 by 20 box use inputs=["0,0,0", "40,30,0", "20"]. \
The second corner's Z coordinate does not supply height.
If a tool reports an error, correct the arguments and retry before \
claiming that the requested geometry was created.
{command_reference}
"""


def build_system_prompt(vision: bool = True) -> str:
    from ..commands.base import _REGISTRY
    lines = []
    for cd in sorted(_REGISTRY.values(), key=lambda c: c.name):
        alias = f" ({', '.join(cd.aliases)})" if cd.aliases else ""
        lines.append(f"  {cd.name}{alias} — {cd.label}")
    prompt = _SYSTEM.format(command_reference="\n".join(lines))
    if not vision:
        prompt = prompt.replace(
            "- After building something non-trivial, call screenshot and LOOK at it. "
            "If it is wrong, fix it before answering. Set an informative view first "
            "(viewport tool: perspective + zoom_extents is a good default).",
            "- This model is text-only and cannot inspect screenshots. Verify work "
            "with scene_info and measure; do not claim to have seen the viewport.")
    return prompt


class Agent(QObject):
    """One conversation with the assistant, bound to a SerpApi."""

    textDelta = Signal(str)
    toolStarted = Signal(str, str)          # tool name, summary
    toolFinished = Signal(str, bool, str)   # name, ok, result summary
    turnFinished = Signal(str)              # stop reason
    errorRaised = Signal(str)
    usageUpdated = Signal(int, int)         # input tokens, output tokens
    conversationReset = Signal()

    _invoke = Signal(object)

    def __init__(self, api, client, max_steps: int = MAX_STEPS_DEFAULT,
                 parent=None):
        super().__init__(parent)
        self.api = api
        self.client = client
        self.max_steps = max_steps
        self.messages: list[dict] = []
        self.system = build_system_prompt(getattr(client, "vision", True))
        self._stop = threading.Event()
        self._reset_requested = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._in_tokens = 0
        self._out_tokens = 0
        self._invoke.connect(self._run_job,
                             Qt.ConnectionType.BlockingQueuedConnection)

    # ------------------------------------------------------------ control

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def send(self, text: str):
        """Start one user turn (returns immediately; signals follow)."""
        with self._state_lock:
            if self.busy or self._reset_requested.is_set():
                return
            self._stop.clear()
            self.messages.append({"role": "user",
                                  "content": self._user_content(text)})
            self._thread = threading.Thread(target=self._turn, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if hasattr(self.client, "interrupt"):
            self.client.interrupt()

    def reset(self):
        """Clear the conversation once any active turn has stopped."""
        with self._state_lock:
            if self.busy:
                self._reset_requested.set()
                self.stop()
                return
            self._clear_conversation()
        self.conversationReset.emit()

    def _clear_conversation(self):
        self.messages.clear()
        self._in_tokens = self._out_tokens = 0
        self._reset_requested.clear()

    # ------------------------------------------------------- turn machinery

    def _user_content(self, text: str):
        # called from send() on the main thread — direct access is safe
        # (and _on_main would deadlock here)
        try:
            selected = [o.name for o in self.api.selection.objects()]
        except Exception:                                     # noqa: BLE001
            selected = []
        if selected:
            text += f"\n\n[currently selected: {', '.join(selected)}]"
        return text

    def _turn(self):
        try:
            for _ in range(self.max_steps):
                if self._stop.is_set():
                    self.turnFinished.emit("stopped")
                    return
                reply = self.client.stream_message(
                    system=self.system, messages=self.messages,
                    tools=T.TOOLS, on_text=self.textDelta.emit,
                    should_stop=self._stop.is_set)
                self._track_usage(reply.get("usage") or {})
                if self._stop.is_set() or reply["stop_reason"] == "aborted":
                    self.turnFinished.emit("stopped")
                    return
                self.messages.append({"role": "assistant",
                                      "content": reply["content"]})
                calls = [b for b in reply["content"]
                         if b.get("type") == "tool_use"]
                if not calls:
                    self.turnFinished.emit(reply["stop_reason"] or "done")
                    return
                results = [self._run_tool(c) for c in calls]
                self.messages.append({"role": "user", "content": results})
            self.turnFinished.emit("step limit reached")
        except (AiError, ApiError) as exc:
            self._drop_dangling_tool_use()
            self.errorRaised.emit(str(exc))
        except Exception as exc:                              # noqa: BLE001
            traceback.print_exc()
            self._drop_dangling_tool_use()
            self.errorRaised.emit(f"{type(exc).__name__}: {exc}")
        finally:
            # Serialize the final reset with New chat and send(), including
            # a reset requested just as the worker is completing.
            with self._state_lock:
                reset = self._reset_requested.is_set()
                if reset:
                    self._clear_conversation()
                self._thread = None
            if reset:
                self.conversationReset.emit()

    def _run_tool(self, call: dict) -> dict:
        name, args = call["name"], call.get("input") or {}
        self.toolStarted.emit(name, T.summarize_call(name, args))
        base = {"type": "tool_result", "tool_use_id": call["id"]}
        if self._stop.is_set():
            self.toolFinished.emit(name, False, "stopped")
            return {**base, "content": "aborted by user", "is_error": True}
        try:
            result = self._on_main(lambda: self._dispatch_tool(name, args))
        except (ApiError, ValueError, TypeError, KeyError) as exc:
            self.toolFinished.emit(name, False, str(exc))
            return {**base, "content": str(exc), "is_error": True}
        if isinstance(result, T.ImageResult):
            self.toolFinished.emit(name, True, result.note)
            return {**base, "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png",
                            "data": base64.b64encode(result.data).decode()}},
            ]}
        self.toolFinished.emit(name, True, _clip(result))
        return {**base, "content": result}

    def _dispatch_tool(self, name: str, args: dict):
        # Check again on the main thread: Stop may arrive while a tool was
        # queued, or the user may have started a CAD prompt during HTTP I/O.
        if self._stop.is_set():
            raise ApiError("Operation stopped before execution.")
        with self.api.external_operation(name, args, source="AI",
                                         summary=T.summarize_call(name, args)):
            if name == "screenshot" and not getattr(self.client, "vision", True):
                raise ApiError("This model has no vision support; use scene_info or measure for text-only verification.")
            return T.dispatch(self.api, name, args)

    def _drop_dangling_tool_use(self):
        """A turn that dies after an assistant tool_use message would leave
        the transcript unsendable (tool_use with no tool_result) — trim it.

        A completed tool/result pair must survive a later network error:
        those operations already happened in the user's scene.
        """
        if not self.messages:
            return
        last = self.messages[-1]
        content = last.get("content")
        if (last["role"] == "assistant" and isinstance(content, list)
                and any(b.get("type") == "tool_use" for b in content)):
            self.messages.pop()

    def _track_usage(self, usage: dict):
        self._in_tokens += int(usage.get("input_tokens") or 0)
        self._out_tokens += int(usage.get("output_tokens") or 0)
        self.usageUpdated.emit(self._in_tokens, self._out_tokens)

    # ------------------------------------------------- main-thread dispatch

    def _on_main(self, fn):
        job = {"fn": fn, "done": threading.Event()}
        self._invoke.emit(job)
        job["done"].wait(timeout=180)
        if "error" in job:
            raise job["error"]
        return job.get("result")

    def _run_job(self, job):
        try:
            job["result"] = job["fn"]()
        except Exception as exc:                              # noqa: BLE001
            job["error"] = exc
        finally:
            job["done"].set()


def _clip(text: str, n: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"
