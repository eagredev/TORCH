# TORCH_MODULE: Web Events
# TORCH_GROUP: Web
"""SSE event broadcaster for the TORCH web GUI.

Provides a global EventBroadcaster that pushes Server-Sent Events to all
connected browser clients.  Stdlib-only — no third-party dependencies.
"""

import json
import queue
import threading
import time


class EventBroadcaster:
    """Fan-out broadcaster for Server-Sent Events."""

    def __init__(self):
        self._clients = set()
        self._lock = threading.Lock()
        self._heartbeat_started = False
        self._on_last_disconnect = None  # callback when last client leaves

    def subscribe(self):
        """Register a new client. Returns a Queue that receives SSE messages."""
        q = queue.Queue(maxsize=256)
        with self._lock:
            self._clients.add(q)
            if not self._heartbeat_started:
                self._heartbeat_started = True
                t = threading.Thread(target=self._heartbeat_loop, daemon=True)
                t.start()
        return q

    def unsubscribe(self, q):
        """Remove a client queue from the broadcaster."""
        with self._lock:
            self._clients.discard(q)
            remaining = len(self._clients)
        if remaining == 0 and self._on_last_disconnect:
            self._on_last_disconnect()

    def broadcast(self, event_type, data):
        """Push an event to all connected clients.

        Silently drops messages for clients whose queues are full.
        """
        msg = format_sse(event_type, data)
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.discard(q)

    @property
    def client_count(self):
        """Number of currently connected clients."""
        with self._lock:
            return len(self._clients)

    def _heartbeat_loop(self):
        """Send a heartbeat comment every 30 seconds to keep connections alive."""
        while True:
            time.sleep(30)
            with self._lock:
                if not self._clients:
                    continue
            # SSE comment (not a real event) — keeps the connection alive
            self.broadcast("heartbeat", {})


def format_sse(event_type, data):
    """Format a single SSE message.

    Returns bytes ready to write to the response stream.
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


# Module-level singleton
broadcaster = EventBroadcaster()
