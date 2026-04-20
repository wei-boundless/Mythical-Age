from __future__ import annotations

from pathlib import Path

from .dialogue_state import DialogueState
from .flow_snapshots import FlowSnapshot, FlowSnapshotManager
from .models import Message
from .process_state import ProcessStateManager
from .session_memory_view import DEFAULT_TEMPLATE, SessionMemoryViewBuilder
from .session_processor import SessionUnderstandingProcessor
from .text_utils import normalize_storage_text


class SessionMemoryManager:
    """Maintains per-session working memory as a rendered process-state view."""

    def __init__(self, session_dir: str | Path) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.views_dir = self.session_dir / "views"
        self.views_dir.mkdir(parents=True, exist_ok=True)
        self.agent_view_path = self.views_dir / "agent_view.md"
        self.compaction_view_path = self.views_dir / "compaction_view.md"
        self.summary_path = self.session_dir / "summary.md"
        self.state_manager = ProcessStateManager(self.session_dir)
        self.flow_snapshot_manager = FlowSnapshotManager(self.session_dir)
        self.processor = SessionUnderstandingProcessor()
        self.view_builder = SessionMemoryViewBuilder()
        self._ensure_view_files()

    def load(self) -> str:
        source_path = self.agent_view_path if self.agent_view_path.exists() else self.summary_path
        return normalize_storage_text(source_path.read_text(encoding="utf-8")) + "\n"

    def load_state(self) -> DialogueState:
        return self.state_manager.load()

    def load_flow_snapshots(self) -> list[FlowSnapshot]:
        return self.flow_snapshot_manager.load()

    def overwrite(self, content: str) -> None:
        normalized = normalize_storage_text(content)
        rendered = normalized + "\n"
        compaction_rendered = self.view_builder.render_compaction_view(rendered)
        self.agent_view_path.write_text(rendered, encoding="utf-8")
        self.summary_path.write_text(rendered, encoding="utf-8")
        self.compaction_view_path.write_text(compaction_rendered, encoding="utf-8")

    def preview_state(
        self,
        messages: list[Message],
        max_items: int = 6,
        *,
        previous_state: DialogueState | None = None,
    ) -> DialogueState:
        baseline = previous_state if previous_state is not None else self.load_state()
        return self.processor.process(messages, baseline, max_items=max_items)

    def update_from_messages(
        self,
        messages: list[Message],
        max_items: int = 6,
        *,
        persist: bool = True,
    ) -> str:
        previous_state = self.load_state()
        state = self.preview_state(messages, max_items=max_items, previous_state=previous_state)
        content = self._render_state(state)
        if persist:
            self.overwrite(content)
            self.state_manager.overwrite(state)
            self.flow_snapshot_manager.update_for_transition(previous_state, state)
        return content

    def compact_view(
        self,
        max_chars_per_section: int = 800,
        *,
        content: str | None = None,
    ) -> str:
        if content is not None:
            return self.view_builder.render_compaction_view(
                content,
                max_chars_per_section=max_chars_per_section,
            )
        if max_chars_per_section == 800 and self.compaction_view_path.exists():
            return normalize_storage_text(self.compaction_view_path.read_text(encoding="utf-8")) + "\n"
        source = self.load()
        return self.view_builder.render_compaction_view(
            source,
            max_chars_per_section=max_chars_per_section,
        )

    def _render_state(self, state: DialogueState) -> str:
        return self.view_builder.render_state(state)

    def _parse_sections(self, content: str) -> dict[str, list[str]]:
        return self.view_builder.parse_sections(content)

    def parse_sections(self, content: str) -> dict[str, list[str]]:
        return self._parse_sections(content)

    def _description_for_header(self, header: str) -> list[str]:
        return self.view_builder.description_for_header(header)

    def describe_storage(self) -> dict[str, object]:
        return {
            "primary_state_path": str(self.state_manager.process_state_path),
            "state_mirror_path": str(self.state_manager.state_mirror_path),
            "flow_snapshot_path": str(self.flow_snapshot_manager.snapshot_path),
            "primary_view_path": str(self.agent_view_path),
            "primary_compaction_view_path": str(self.compaction_view_path),
            "view_mirror_path": str(self.summary_path),
            "primary_state_exists": self.state_manager.process_state_path.exists(),
            "state_mirror_exists": self.state_manager.state_mirror_path.exists(),
            "flow_snapshot_exists": self.flow_snapshot_manager.snapshot_path.exists(),
            "primary_view_exists": self.agent_view_path.exists(),
            "primary_compaction_view_exists": self.compaction_view_path.exists(),
            "view_mirror_exists": self.summary_path.exists(),
        }

    def _ensure_view_files(self) -> None:
        if self.agent_view_path.exists():
            source = self.agent_view_path.read_text(encoding="utf-8")
            if not self.summary_path.exists():
                self.summary_path.write_text(source, encoding="utf-8")
            if not self.compaction_view_path.exists():
                self.compaction_view_path.write_text(
                    self.view_builder.render_compaction_view(source),
                    encoding="utf-8",
                )
            return
        if self.summary_path.exists():
            source = self.summary_path.read_text(encoding="utf-8")
            self.agent_view_path.write_text(source, encoding="utf-8")
            self.compaction_view_path.write_text(
                self.view_builder.render_compaction_view(source),
                encoding="utf-8",
            )
            return
        default_view = DEFAULT_TEMPLATE
        self.agent_view_path.write_text(default_view, encoding="utf-8")
        self.summary_path.write_text(default_view, encoding="utf-8")
        self.compaction_view_path.write_text(
            self.view_builder.render_compaction_view(default_view),
            encoding="utf-8",
        )
