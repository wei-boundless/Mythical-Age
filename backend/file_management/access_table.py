from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import casbin
from casbin import persist

from .models import FileAccessRule, ManagedFileRepositorySpec
from .resolver import ResolvedFileEnvironment


@dataclass(frozen=True, slots=True)
class FileAccessGrant:
    repository_id: str
    repository_kind: str
    action: str
    behavior: str
    source: str
    reason: str = ""
    requires_review_receipt: bool = False
    requires_commit_gate: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.behavior == "allow"

    @property
    def requires_approval(self) -> bool:
        return self.behavior == "ask" or self.requires_commit_gate or self.requires_review_receipt

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileAccessDeny:
    repository_id: str
    repository_kind: str
    action: str
    reason: str
    source: str = "file_access_table"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileAccessTable:
    table_id: str
    profile_id: str
    grants: tuple[FileAccessGrant, ...] = ()
    denials: tuple[FileAccessDeny, ...] = ()
    source_trace: tuple[str, ...] = ()
    policy_backend: str = "casbin"
    authority: str = "file_management.file_access_table"

    def grants_for(self, *, repository_id: str = "", action: str = "") -> tuple[FileAccessGrant, ...]:
        repo = str(repository_id or "").strip()
        act = str(action or "").strip()
        return tuple(
            grant
            for grant in self.grants
            if (not repo or grant.repository_id == repo) and (not act or grant.action == act)
        )

    def is_allowed(self, *, repository_id: str, action: str) -> bool:
        return any(grant.allowed for grant in self.grants_for(repository_id=repository_id, action=action))

    def requires_approval(self, *, repository_id: str, action: str) -> bool:
        return any(grant.requires_approval for grant in self.grants_for(repository_id=repository_id, action=action))

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "profile_id": self.profile_id,
            "grants": [grant.to_dict() for grant in self.grants],
            "denials": [denial.to_dict() for denial in self.denials],
            "source_trace": list(self.source_trace),
            "policy_backend": self.policy_backend,
            "authority": self.authority,
        }


def build_file_access_table(
    environment: ResolvedFileEnvironment,
    *,
    task_file_requirements: dict[str, dict[str, Any]] | None = None,
    agent_allowed_actions: tuple[str, ...] | list[str] = (),
    table_id: str = "",
) -> FileAccessTable:
    requirements = dict(task_file_requirements or {})
    agent_actions = {str(item or "").strip() for item in list(agent_allowed_actions or []) if str(item or "").strip()}
    grants: list[FileAccessGrant] = []
    denials: list[FileAccessDeny] = []
    enforcer = _build_enforcer(environment.repositories)

    for repo in environment.repositories:
        actions = _candidate_actions(repo, requirements.get(repo.repository_id, {}))
        for action in actions:
            if agent_actions and action not in agent_actions:
                denials.append(
                    FileAccessDeny(
                        repository_id=repo.repository_id,
                        repository_kind=repo.repository_kind,
                        action=action,
                        reason="filtered by agent file action ceiling",
                        source="agent_profile",
                    )
                )
                continue
            decision_rule = _effective_rule(repo, action)
            if decision_rule is None:
                denials.append(
                    FileAccessDeny(
                        repository_id=repo.repository_id,
                        repository_kind=repo.repository_kind,
                        action=action,
                        reason="no file access rule",
                    )
                )
                continue
            if decision_rule.behavior == "deny" or not enforcer.enforce("runtime", repo.repository_id, action):
                denials.append(
                    FileAccessDeny(
                        repository_id=repo.repository_id,
                        repository_kind=repo.repository_kind,
                        action=action,
                        reason=decision_rule.reason or "denied by file access policy",
                        source=decision_rule.source,
                    )
                )
                continue
            grants.append(
                FileAccessGrant(
                    repository_id=repo.repository_id,
                    repository_kind=repo.repository_kind,
                    action=action,
                    behavior=decision_rule.behavior,
                    source=decision_rule.source,
                    reason=decision_rule.reason,
                    requires_review_receipt=decision_rule.requires_review_receipt,
                    requires_commit_gate=decision_rule.requires_commit_gate,
                    metadata={
                        "canonical": repo.canonical,
                        "commit_required": repo.commit_required,
                        **dict(decision_rule.metadata),
                    },
                )
            )

    return FileAccessTable(
        table_id=table_id or f"file-access:{environment.profile_id}",
        profile_id=environment.profile_id,
        grants=tuple(grants),
        denials=tuple(denials),
        source_trace=(
            f"profile:{environment.profile_id}",
            "policy_backend:casbin",
            "task_requirements:file_management",
            "agent_profile:file_action_ceiling",
        ),
    )


def _candidate_actions(repo: ManagedFileRepositorySpec, requirement: dict[str, Any]) -> tuple[str, ...]:
    explicit = [str(item or "").strip() for item in list(requirement.get("actions") or []) if str(item or "").strip()]
    if explicit:
        return tuple(dict.fromkeys(explicit))
    actions: list[str] = []
    actions.extend(
        str(rule.action or "").strip()
        for rule in repo.access_rules
        if str(rule.action or "").strip() and str(rule.action or "").strip() != "*"
    )
    if repo.readable:
        actions.extend(["open", "read"])
    if repo.searchable:
        actions.append("search")
    if repo.writable:
        actions.extend(["write", "edit"])
    if repo.commit_required or repo.canonical:
        actions.append("commit")
    if repo.rollback_supported:
        actions.append("rollback")
    return tuple(dict.fromkeys(actions))


def _effective_rule(repo: ManagedFileRepositorySpec, action: str) -> FileAccessRule | None:
    rules = repo.rules_for_action(action)
    if not rules:
        return None
    deny = next((rule for rule in rules if rule.behavior == "deny"), None)
    if deny is not None:
        return deny
    ask = next((rule for rule in rules if rule.behavior == "ask"), None)
    if ask is not None:
        return ask
    return rules[0]


def _build_enforcer(repositories: tuple[ManagedFileRepositorySpec, ...]) -> casbin.Enforcer:
    model = casbin.Model()
    model.load_model_from_text(
        """
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act, eft

[policy_effect]
e = some(where (p.eft == allow)) && !some(where (p.eft == deny))

[matchers]
m = (p.sub == r.sub || p.sub == "*") && (p.obj == r.obj || p.obj == "*") && (p.act == r.act || p.act == "*")
"""
    )
    enforcer = casbin.Enforcer(model, _MemoryPolicyAdapter(_policies_for_repositories(repositories)))
    return enforcer


def _policies_for_repositories(repositories: tuple[ManagedFileRepositorySpec, ...]) -> list[list[str]]:
    policies: list[list[str]] = []
    for repo in repositories:
        for rule in repo.access_rules:
            effect = "allow" if rule.behavior in {"allow", "ask"} else "deny"
            policies.append(["p", "runtime", repo.repository_id, rule.action, effect])
    return policies


class _MemoryPolicyAdapter(persist.Adapter):
    def __init__(self, policies: list[list[str]]) -> None:
        self.policies = policies

    def load_policy(self, model: casbin.Model) -> None:
        for policy in self.policies:
            persist.load_policy_line(", ".join(policy), model)

    def save_policy(self, model: casbin.Model) -> bool:
        return False
