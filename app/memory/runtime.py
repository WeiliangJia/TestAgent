from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeMemory:
    """L2 — execution-scoped memory for a single test run.

    Holds ephemeral facts and events observed during the current run. Discarded
    after the run completes; a digest may be promoted into L1 by MemorySystem.
    """

    project_id: str
    test_id: str
    facts: dict[str, Any] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def put(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.facts.get(key, default)

    def record(self, event: str) -> None:
        self.events.append(event)

    def to_prompt_context(self) -> str:
        if not self.facts and not self.events:
            return f"L2 (runtime {self.test_id}): no events yet."
        lines = [f"L2 (runtime {self.test_id}):"]
        for key, value in self.facts.items():
            lines.append(f"- {key}: {value}")
        if self.events:
            lines.append("- events:")
            lines.extend(f"  * {event}" for event in self.events[-10:])
        return "\n".join(lines)
