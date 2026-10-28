"""Public agent narration, never reasoning or tool result bodies."""

from __future__ import annotations
import time


class AgentOutput:
    def __init__(self, emit=None):
        self.emit = emit
        self.parts = {}
        self.roles = {}

    def accept(self, event):
        if not self.emit:
            return
        properties = event.get("properties", {})
        kind = event.get("type")
        if kind == "message.updated":
            info = properties.get("info", {})
            self.roles[info.get("id")] = info.get("role")
            for part in self.parts.values():
                if part.get("messageID") == info.get("id"):
                    self.publish(part)
        elif kind == "message.part.updated":
            part = properties.get("part", {})
            if part.get("id"):
                previous = self.parts.get(part["id"], {})
                part = dict(part)
                if not part.get("text") and "type" not in previous and previous.get("text"):
                    part["text"] = previous["text"]
                self.parts[part["id"]] = part
                self.publish(part)
        elif kind == "message.part.delta" and properties.get("field") == "text":
            pid = properties.get("partID")
            if not pid:
                return
            part = self.parts.setdefault(pid, {"id": pid, "messageID": properties.get("messageID")})
            part["text"] = (part.get("text", "") + properties.get("delta", ""))[-32000:]
            self.publish(part)

    def publish(self, part):
        if self.roles.get(part.get("messageID")) != "assistant":
            return
        if part.get("type") == "text" and part.get("text"):
            self.emit({"id": part["id"], "kind": "text", "text": part["text"][-32000:]})
        elif part.get("type") == "tool":
            state = part.get("state", {})
            self.emit(
                {
                    "id": part["id"],
                    "kind": "tool",
                    "text": str(state.get("title") or part.get("tool", "Inspecting source"))[:500],
                    "status": state.get("status", "pending"),
                }
            )


class MapActivity:
    """Bounded transcript snapshots, with disk writes throttled during token bursts."""

    def __init__(self, save):
        self.save = save
        self.events = []
        self.last_flush = 0
        self.last_activity = time.time()

    def emit(self, event):
        now = time.time()
        value = {**event, "text": str(event.get("text", ""))[-32000:]}
        existing = next((e for e in self.events if e["id"] == value["id"]), None)
        if existing and all(existing.get(k) == v for k, v in value.items()):
            return
        if existing:
            existing.update(value)
        else:
            self.events.append({**value, "at": now})
        while len(self.events) > 200 or sum(len(e["text"]) for e in self.events) > 160000:
            self.events.pop(0)
        self.last_activity = now
        if time.monotonic() - self.last_flush > 0.2:
            self.flush()

    def status(self, text):
        # Agent text already arrives with stable IDs; progress is for short stages.
        if text.startswith(
            ("Starting OpenCode", "Retrying OpenCode", "Exploring source", "Fixing validation")
        ):
            self.emit({"id": f"status-{time.time_ns()}", "kind": "status", "text": text})

    def flush(self):
        self.save(list(self.events), self.last_activity)
        self.last_flush = time.monotonic()
