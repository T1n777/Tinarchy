import time
import json
import queue
import threading
from typing import Set, Optional

class SSEBroker:
    """Thread-safe Server-Sent Events broker and subscriber manager.
    Broadcasts real-time telemetry updates to connected browser clients.
    Automatically idles collection when zero clients are active.
    """

    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._subscribers: Set[queue.Queue] = set()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._syncthing_module = None

    def set_syncthing_module(self, syncthing_module):
        self._syncthing_module = syncthing_module

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=40)
        with self._lock:
            self._subscribers.add(q)
            if not self._running:
                self.start()
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subscribers.discard(q)

    def client_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def broadcast(self, event_type: str, data: dict):
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode('utf-8')
        with self._lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    # Drop frame for lagging client to prevent unbounded memory growth
                    pass

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._broadcast_loop, daemon=True, name="SSEBrokerLoop")
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False

    def _broadcast_loop(self):
        from tinarchy.telemetry import collect_full_system_snapshot
        while self._running:
            try:
                # If no active clients are connected, sleep to consume 0 CPU
                if self.client_count() == 0:
                    time.sleep(2.0)
                    continue

                snapshot = collect_full_system_snapshot(self._syncthing_module)
                self.broadcast("telemetry", snapshot)
            except Exception as e:
                pass
            time.sleep(self.interval)

# Global singleton broker
sse_broker = SSEBroker(interval=2.0)
