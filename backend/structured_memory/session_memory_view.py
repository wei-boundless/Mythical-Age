from __future__ import annotations

from .dialogue_state import DialogueState


DEFAULT_TEMPLATE = """# Session Title
_A short and distinctive title for the session._

# Active Goal
_What is the user currently trying to achieve?_

# Flow State
_What workflow is currently active, and how confident is the system about it?_

# Context Slots
_Which contextual bindings are active for the current workflow?_

# Current Task State
_What is currently in progress or waiting to be done?_

# Warm Context
_Still-useful prior context from earlier in this session._

# Key User Requests
_Stable instructions or constraints from the user within this session._

# Files and Functions
_Important files, modules, and functions relevant to the current work._

# Workflow and Constraints
_Commands, operational habits, and environment constraints that matter now._

# Errors and Corrections
_Failures, corrections, and approaches to avoid repeating._

# Decisions and Learnings
_Concrete conclusions, tradeoffs, and learnings established in this session._

# Key Results
_Exact outputs, conclusions, or artifacts already produced for the user._

# Risk Watch
_Known risks in current session state and active safeguards._

# Next Step
_What the assistant should most likely do next if the work continues._

# Durable Candidates
_Potential long-term memories distilled from this session state._

# Worklog
_Short chronological bullets of meaningful events._
"""

COMPACTION_HEADER_ORDER = [
    "# Session Title",
    "# Active Goal",
    "# Flow State",
    "# Context Slots",
    "# Current Task State",
    "# Next Step",
    "# Risk Watch",
    "# Key User Requests",
    "# Files and Functions",
    "# Workflow and Constraints",
    "# Errors and Corrections",
    "# Decisions and Learnings",
    "# Key Results",
    "# Warm Context",
    "# Durable Candidates",
    "# Worklog",
]

COMPACTION_SECTION_LIMITS = {
    "# Session Title": 80,
    "# Active Goal": 220,
    "# Flow State": 260,
    "# Context Slots": 220,
    "# Current Task State": 320,
    "# Next Step": 220,
    "# Risk Watch": 220,
    "# Key User Requests": 220,
    "# Files and Functions": 220,
    "# Workflow and Constraints": 220,
    "# Errors and Corrections": 220,
    "# Decisions and Learnings": 240,
    "# Key Results": 260,
    "# Warm Context": 220,
    "# Durable Candidates": 180,
    "# Worklog": 180,
}


class SessionMemoryViewBuilder:
    def render_state(self, state: DialogueState) -> str:
        sections = {
            "# Session Title": [state.session_title or "Ongoing session"],
            "# Active Goal": self._to_bullets([state.active_goal] if state.active_goal else []),
            "# Flow State": self._to_bullets(self._flow_lines(state)),
            "# Context Slots": self._to_bullets(self._context_slot_lines(state)),
            "# Current Task State": self._to_bullets(state.current_task_state),
            "# Warm Context": self._to_bullets(state.warm_context),
            "# Key User Requests": self._to_bullets(state.key_user_requests),
            "# Files and Functions": self._to_bullets(state.files_and_functions),
            "# Workflow and Constraints": self._to_bullets(state.workflow_and_constraints),
            "# Errors and Corrections": self._to_bullets(state.errors_and_corrections),
            "# Decisions and Learnings": self._to_bullets(state.decisions_and_learnings),
            "# Key Results": self._to_bullets(state.key_results),
            "# Risk Watch": self._to_bullets(state.risk_notes or state.risk_flags),
            "# Next Step": self._to_bullets(state.next_step),
            "# Durable Candidates": self._to_bullets(
                [self._render_candidate(item) for item in state.durable_candidates]
            ),
            "# Worklog": self._to_bullets(state.worklog),
        }
        return self._render_sections(sections)

    def compact_view(
        self,
        source: str,
        *,
        max_chars_per_section: int = 800,
    ) -> str:
        return self.render_compaction_view(source, max_chars_per_section=max_chars_per_section)

    def render_compaction_view(
        self,
        source: str,
        *,
        max_chars_per_section: int = 800,
    ) -> str:
        sections = self.parse_sections(source)
        rendered: list[str] = []
        ordered_headers = [
            header
            for header in COMPACTION_HEADER_ORDER
            if header in sections
        ] or list(sections.keys())
        for header in ordered_headers:
            body = sections.get(header, [])
            rendered.append(header)
            rendered.extend(self.description_for_header(header))
            text = "\n".join(body).strip()
            section_limit = min(
                max_chars_per_section,
                COMPACTION_SECTION_LIMITS.get(header, max_chars_per_section),
            )
            if len(text) > section_limit:
                text = text[:section_limit].rstrip() + "\n[... section truncated ...]"
            if text:
                rendered.append(text)
            rendered.append("")
        return "\n".join(rendered).strip() + "\n"

    def parse_sections(self, content: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current_header: str | None = None
        current_lines: list[str] = []
        for line in content.splitlines():
            if line.startswith("# "):
                if current_header is not None:
                    sections[current_header] = current_lines
                current_header = line
                current_lines = []
            else:
                current_lines.append(line)
        if current_header is not None:
            sections[current_header] = current_lines
        if not sections:
            return self.parse_sections(DEFAULT_TEMPLATE)
        return sections

    def description_for_header(self, header: str) -> list[str]:
        template_sections = self.parse_sections(DEFAULT_TEMPLATE)
        return [line for line in template_sections.get(header, []) if line.strip().startswith("_")]

    def _render_sections(self, sections: dict[str, list[str]]) -> str:
        ordered_headers = list(self.parse_sections(DEFAULT_TEMPLATE).keys())
        chunks: list[str] = []
        for header in ordered_headers:
            chunks.append(header)
            lines = sections.get(header, [])
            description = self.description_for_header(header)
            chunks.extend(description)
            body = [line for line in lines if line not in description]
            body = [line for line in body if line.strip()]
            if body:
                chunks.extend(body)
            chunks.append("")
        return "\n".join(chunks).strip() + "\n"

    def _flow_lines(self, state: DialogueState) -> list[str]:
        flow = state.flow_state
        task = state.task_state
        items = [
            f"当前流程类型：{flow.flow_type}",
            f"流程状态：{flow.status}",
            f"流程置信度：{round(flow.confidence, 2)}",
        ]
        if task.current_step:
            items.append(f"当前步骤：{task.current_step}")
        if task.next_step:
            items.append(f"下一步：{task.next_step}")
        return [item for item in items if item.strip()]

    def _context_slot_lines(self, state: DialogueState) -> list[str]:
        slots = state.context_slots
        items: list[str] = []
        if slots.active_pdf:
            items.append(f"当前 PDF：{slots.active_pdf}")
        if slots.active_dataset:
            items.append(f"当前数据集：{slots.active_dataset}")
        if slots.active_entity:
            items.append(f"当前实体：{slots.active_entity}")
        if slots.active_rule:
            items.append(f"当前规则：{slots.active_rule}")
        return items

    def _render_candidate(self, candidate) -> str:
        label = f"{candidate.memory_class}/{candidate.memory_type}"
        return f"[{label}] {candidate.canonical_statement}"

    def _to_bullets(self, items: list[str]) -> list[str]:
        return [f"- {item}" for item in items if item.strip()]
