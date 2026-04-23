from __future__ import annotations

from .dialogue_state import DialogueState


DEFAULT_TEMPLATE = """# Session Title
_A short and distinctive title for the session._

# Active Goal
_What is the user currently trying to achieve?_

# Flow State
_What flow is currently active, and how confident is the system about it?_

# Context Slots
_Which contextual bindings are active for the current flow?_

# Current Task State
_What is currently in progress or waiting to be done?_

# Warm Context
_Still-useful prior context from earlier in this session._

# Key User Requests
_Stable instructions or constraints from the user within this session._

# Files and Functions
_Important files, modules, and functions relevant to the current work._

# Conventions and Constraints
_Commands, operating conventions, and environment constraints that matter now._

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
    "# Conventions and Constraints",
    "# Errors and Corrections",
    "# Decisions and Learnings",
    "# Key Results",
    "# Warm Context",
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
    "# Conventions and Constraints": 220,
    "# Errors and Corrections": 220,
    "# Decisions and Learnings": 240,
    "# Key Results": 260,
    "# Warm Context": 220,
    "# Worklog": 180,
}


class SessionMemoryViewBuilder:
    def render_state(self, state: DialogueState, *, mode: str = "debug") -> str:
        include_debug = mode != "model"
        sections = {
            "# Session Title": [state.session_title or "Ongoing session"],
            "# Active Goal": self._to_bullets([state.active_goal] if state.active_goal else []),
            "# Flow State": self._to_bullets(self._flow_lines(state, include_debug=include_debug)),
            "# Context Slots": self._to_bullets(self._context_slot_lines(state, include_debug=include_debug)),
            "# Current Task State": self._to_bullets(
                state.current_task_state if include_debug else self._model_current_task_lines(state)
            ),
            "# Warm Context": self._to_bullets(state.warm_context),
            "# Key User Requests": self._to_bullets(state.key_user_requests),
            "# Files and Functions": self._to_bullets(state.files_and_functions),
            "# Conventions and Constraints": self._to_bullets(state.conventions_and_constraints),
            "# Errors and Corrections": self._to_bullets(state.errors_and_corrections),
            "# Decisions and Learnings": self._to_bullets(state.decisions_and_learnings),
            "# Key Results": self._to_bullets(state.key_results),
            "# Risk Watch": self._to_bullets(state.risk_notes or state.risk_flags) if include_debug else [],
            "# Next Step": self._to_bullets(state.next_step) if include_debug else [],
            "# Worklog": self._to_bullets(state.worklog) if include_debug else [],
        }
        return self._render_sections(sections, include_empty_headers=include_debug)

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

    def _render_sections(self, sections: dict[str, list[str]], *, include_empty_headers: bool) -> str:
        ordered_headers = list(self.parse_sections(DEFAULT_TEMPLATE).keys())
        chunks: list[str] = []
        for header in ordered_headers:
            lines = sections.get(header, [])
            description = self.description_for_header(header)
            body = [line for line in lines if line not in description]
            body = [line for line in body if line.strip()]
            if not include_empty_headers and not body:
                continue
            chunks.append(header)
            chunks.extend(description)
            if body:
                chunks.extend(body)
            chunks.append("")
        return "\n".join(chunks).strip() + "\n"

    def _flow_lines(self, state: DialogueState, *, include_debug: bool) -> list[str]:
        flow = state.flow_state
        task = state.task_state
        items = [
            f"当前流程类型：{flow.flow_type}",
            f"流程状态：{flow.status}",
        ]
        if include_debug:
            items.append(f"流程置信度：{round(flow.confidence, 2)}")
        if include_debug and task.current_step:
            items.append(f"当前步骤：{task.current_step}")
        if (not include_debug) and task.current_step and self._looks_like_result_line(task.current_step):
            items.append(f"最近结果：{task.current_step}")
        if include_debug and task.next_step:
            items.append(f"下一步：{task.next_step}")
        return [item for item in items if item.strip()]

    def _context_slot_lines(self, state: DialogueState, *, include_debug: bool) -> list[str]:
        slots = state.context_slots
        items: list[str] = []
        if slots.active_pdf:
            items.append(f"当前 PDF：{slots.active_pdf}")
        if slots.active_pdf_mode:
            items.append(f"PDF 查询范围：{slots.active_pdf_mode}")
        if slots.active_pdf_section:
            items.append(f"PDF 当前章节：{slots.active_pdf_section}")
        if slots.active_pdf_pages:
            items.append(f"PDF 聚焦页：{', '.join(str(page) for page in slots.active_pdf_pages)}")
        if slots.active_dataset:
            items.append(f"当前数据集：{slots.active_dataset}")
        if include_debug and slots.active_binding_identity:
            items.append(f"当前绑定标识：{slots.active_binding_identity}")
        if include_debug and slots.active_binding_owner_task_id:
            items.append(f"当前绑定 Owner：{slots.active_binding_owner_task_id}")
        if slots.active_entity:
            items.append(f"当前实体：{slots.active_entity}")
        if include_debug and slots.active_rule:
            items.append(f"当前规则：{slots.active_rule}")
        return items

    def _model_current_task_lines(self, state: DialogueState) -> list[str]:
        lines = list(state.current_task_state)
        filtered: list[str] = []
        allowed_prefixes = (
            "当前目标：",
            "当前约束：",
            "最新结果摘要：",
            "当前工作项：",
        )
        for line in lines:
            compact = line.strip()
            if not compact:
                continue
            if not compact.startswith(allowed_prefixes):
                continue
            filtered.append(compact)
        return filtered[:6]

    def _looks_like_result_line(self, text: str) -> bool:
        compact = text.strip()
        if not compact:
            return False
        result_markers = ("已", "完成", "结论", "建议", "发现", "修复", "通过")
        return any(marker in compact for marker in result_markers)

    def _to_bullets(self, items: list[str]) -> list[str]:
        return [f"- {item}" for item in items if item.strip()]
