from __future__ import annotations

from pathlib import Path

from .compact import ContextCompactor
from .extraction_scheduler import ExtractionScheduler
from .extractor import MemoryExtractor
from .memory_manager import MemoryManager
from .models import Message
from .prompt_builder import PromptBuilder
from .session_memory import SessionMemoryManager
from .team_memory import TeamMemoryManager


class DemoAgent:
    """Minimal agent wrapper showing how to integrate the memory system."""

    def __init__(self, workspace: str | Path) -> None:
        workspace = Path(workspace)
        self.memory = MemoryManager(workspace / "durable_memory")
        self.team_memory = TeamMemoryManager(workspace / "durable_memory")
        self.session_memory = SessionMemoryManager(workspace / "session-memory")
        self.compactor = ContextCompactor(
            self.session_memory,
            max_messages=10,
            keep_recent_messages=4,
        )
        self.extractor = MemoryExtractor(self.memory)
        self.scheduler = ExtractionScheduler(self.extractor)
        self.prompt_builder = PromptBuilder(
            self.memory,
            self.session_memory,
            self.compactor,
            self.team_memory,
        )
        self.messages: list[Message] = []

    def receive_user_message(self, content: str) -> str:
        self.messages.append(Message(role="user", content=content))
        self.session_memory.update_from_messages(self.messages)

        runtime_messages = self.prompt_builder.build_runtime_messages(
            "You are a Python agent with file-based memory and session compaction. Use memory when it helps future work.",
            self.messages,
        )
        reply = self._mock_model_reply(runtime_messages, content)

        self.messages.append(Message(role="assistant", content=reply))
        self.session_memory.update_from_messages(self.messages)
        self.scheduler.submit(self.messages)
        return reply

    def _mock_model_reply(
        self,
        runtime_messages: list[Message],
        user_message: str,
    ) -> str:
        """Swap this method out for a real model call."""
        system_prompt = runtime_messages[0].content if runtime_messages else ""
        compacted = any(
            msg.meta.get("kind") == "compact_summary"
            for msg in runtime_messages
            if msg.meta
        )
        memory_hint = ""
        if "Persistent Memory" in system_prompt and "- [" in system_prompt:
            memory_hint = " I also checked saved memory before answering."
        compact_hint = " Prior history was compacted." if compacted else ""
        return f"Processed: {user_message.strip()}.{memory_hint}{compact_hint}"


def main() -> None:
    agent = DemoAgent(Path(".demo-agent"))
    examples = [
        "Remember that I prefer Python examples over TypeScript.",
        "Our project uses FastAPI and pytest.",
        "Please help me design the next endpoint.",
        "Remember that I want concise answers unless I ask for deep detail.",
        "We use pydantic settings for configuration.",
        "Now sketch the auth module layout.",
    ]
    for message in examples:
        response = agent.receive_user_message(message)
        print(f"USER: {message}")
        print(f"AGENT: {response}")
        print("-" * 60)


if __name__ == "__main__":
    main()
