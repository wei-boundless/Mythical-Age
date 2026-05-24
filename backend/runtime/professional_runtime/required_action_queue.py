from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..memory.tool_observation_ledger import ToolObservationLedger
from .goal_contract import ProfessionalTaskGoalContract


@dataclass(frozen=True, slots=True)
class RequiredAction:
    action_id: str
    kind: str
    tool_names: tuple[str, ...]
    path: str = ""
    satisfied: bool = False
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tool_names"] = list(self.tool_names)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class RequiredActionQueue:
    actions: tuple[RequiredAction, ...]
    current_action: RequiredAction | None = None
    authority: str = "orchestration.professional_required_action_queue"

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [action.to_dict() for action in self.actions],
            "current_action": self.current_action.to_dict() if self.current_action is not None else None,
            "missing_obligations": list(self.missing_obligations()),
            "required_tool_names": list(self.required_tool_names()),
            "authority": self.authority,
        }

    def missing_obligations(self) -> tuple[str, ...]:
        return tuple(_obligation_label(action) for action in self.actions if not action.satisfied)

    def required_tool_names(self) -> tuple[str, ...]:
        if self.current_action is None:
            return ()
        return self.current_action.tool_names

    def current_path(self) -> str:
        return self.current_action.path if self.current_action is not None else ""

    def prompt_guidance(self) -> str:
        if self.current_action is None:
            return ""
        if self.current_action.kind == "write_output":
            return (
                f"当前强制动作：使用 write_file 写入 {self.current_action.path}。"
                "本轮不要改写其他路径，不要提前验证或总结。"
            )
        if self.current_action.kind == "verify_command":
            return "当前强制动作：使用 terminal 运行验证命令，并基于真实命令输出收口。"
        if self.current_action.kind == "ensure_dir":
            return f"当前强制动作：使用 write_file 写入 {self.current_action.path}，以确保目录存在。"
        return f"当前强制动作：{_obligation_label(self.current_action)}。"


def build_required_action_queue(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> RequiredActionQueue:
    actions: list[RequiredAction] = []
    for path in list(goal_contract.required_output_paths or []):
        normalized_path = str(path or "").strip().replace("\\", "/")
        is_directory = normalized_path.endswith("/") or "." not in normalized_path.rsplit("/", 1)[-1]
        if is_directory:
            keep_path = normalized_path.strip("/") + "/.keep"
            satisfied = tool_observation_ledger.has_write(keep_path) or any(
                _path_matches(normalized_path, observed)
                for observed in tool_observation_ledger.observed_paths()
            )
            actions.append(
                RequiredAction(
                    action_id=f"ensure_dir:{normalized_path.strip('/')}",
                    kind="ensure_dir",
                    tool_names=("write_file",),
                    path=keep_path,
                    satisfied=satisfied,
                    evidence_refs=_refs_for(tool_observation_ledger, "write_output"),
                )
            )
            continue
        evidence_refs = tuple(
            record.observation_ref
            for record in tool_observation_ledger.records
            if record.observation_ref and "write_output" in record.satisfies and tool_observation_ledger.has_write(normalized_path)
        )
        actions.append(
            RequiredAction(
                action_id=f"write:{normalized_path}",
                kind="write_output",
                tool_names=("write_file",),
                path=normalized_path,
                satisfied=tool_observation_ledger.has_write(normalized_path),
                evidence_refs=evidence_refs,
            )
        )
    if goal_contract.requires_write_output and not goal_contract.required_output_paths:
        actions.append(
            RequiredAction(
                action_id="write:any",
                kind="write_output",
                tool_names=("write_file", "edit_file"),
                satisfied=tool_observation_ledger.has_write(),
                evidence_refs=_refs_for(tool_observation_ledger, "write_output"),
            )
        )
    if goal_contract.requires_verification_command:
        writes_satisfied = all(action.satisfied for action in actions if action.kind in {"write_output", "ensure_dir"})
        actions.append(
            RequiredAction(
                action_id="verify:terminal",
                kind="verify_command",
                tool_names=("terminal",),
                satisfied=bool(writes_satisfied and tool_observation_ledger.verification_passed()),
                evidence_refs=_refs_for(tool_observation_ledger, "verify_command"),
            )
        )
    current = next((action for action in actions if not action.satisfied), None)
    return RequiredActionQueue(actions=tuple(actions), current_action=current)


def _refs_for(ledger: ToolObservationLedger, obligation_key: str) -> tuple[str, ...]:
    return tuple(
        record.observation_ref
        for record in ledger.records
        if obligation_key in record.satisfies and record.observation_ref
    )


def _obligation_label(action: RequiredAction) -> str:
    if action.kind == "write_output" and action.path:
        return f"write_output:{action.path}"
    if action.kind == "ensure_dir" and action.path:
        return f"ensure_dir:{action.path.rsplit('/', 1)[0]}"
    return action.kind


def _path_matches(target: str, candidate: str) -> bool:
    normalized_target = str(target or "").strip().strip("/").replace("\\", "/").lower()
    normalized_candidate = str(candidate or "").strip().strip("/").replace("\\", "/").lower()
    return bool(
        normalized_target
        and normalized_candidate
        and (
            normalized_candidate == normalized_target
            or normalized_candidate.startswith(normalized_target + "/")
            or normalized_target.startswith(normalized_candidate + "/")
        )
    )
