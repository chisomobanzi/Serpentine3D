"""Background model discovery shared by Assistant setup and Settings."""

import threading

from PySide6.QtCore import QObject, Signal


class ModelDiscovery(QObject):
    finished = Signal(str, object, str)

    def start(self, endpoint: str):
        def fetch():
            from .local_client import discover_models
            try:
                models, error = discover_models(endpoint), ""
            except Exception as exc:
                models, error = [], str(exc)
            try:
                self.finished.emit(endpoint, models, error)
            except RuntimeError:
                # Its owning panel/dialog may close while HTTP is in flight.
                pass
        threading.Thread(target=fetch, daemon=True).start()
