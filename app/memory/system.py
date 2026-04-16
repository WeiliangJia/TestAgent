from __future__ import annotations

from pathlib import Path

from app.memory.permanent import PermanentMemory
from app.memory.project import ProjectMemory
from app.memory.runtime import RuntimeMemory


class MemorySystem:
    """Three-tier memory façade used by the orchestrator.

    - L0 (PermanentMemory): global, agent-wide. Spec templates + assertion rules.
    - L1 (ProjectMemory):   per project_id. PRD summaries + past run digests.
    - L2 (RuntimeMemory):   per test run. Ephemeral facts and events.
    """

    def __init__(self, *, sqlite_path: Path) -> None:
        self.l0 = PermanentMemory(sqlite_path)
        self.l1 = ProjectMemory(sqlite_path)

    def initialize(self) -> None:
        self.l0.initialize()
        self.l1.initialize()

    def new_runtime(self, *, project_id: str, test_id: str) -> RuntimeMemory:
        return RuntimeMemory(project_id=project_id, test_id=test_id)

    def to_prompt_context(
        self, *, project_id: str, runtime: RuntimeMemory | None = None
    ) -> str:
        parts = [
            self.l0.to_prompt_context(),
            self.l1.to_prompt_context(project_id=project_id),
        ]
        if runtime is not None:
            parts.append(runtime.to_prompt_context())
        return "\n\n".join(parts)

    def snapshot(
        self, *, project_id: str, runtime: RuntimeMemory | None = None
    ) -> dict[str, str]:
        return {
            "L0": self.l0.to_prompt_context(),
            "L1": self.l1.to_prompt_context(project_id=project_id),
            "L2": runtime.to_prompt_context() if runtime is not None else "",
        }
