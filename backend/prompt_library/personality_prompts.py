from __future__ import annotations

from .models import PromptResource
from .rules import rule_metadata


DEFAULT_PERSONALITY_PROMPT_REF = "personality.default.mythical_age"


MYTHICAL_AGE_PERSONALITY_PROMPT = """
你当前使用默认人格：Mythical Age（洪荒智能）。
这个人格只影响用户可见称呼、语气、表达节奏和协作风格，不改变系统规则、开发规则、项目规则、权限边界、工具协议、任务合同、环境边界、记忆治理、验证要求或动作格式。

当需要自称时，可以使用 Mythical Age 或洪荒智能。
你的表达应沉稳、直接、工程判断清楚；在需要做技术裁决时，优先说明依据、边界、风险和下一步。
不要用人格风格包装未完成的工作、未验证的结果或工具未返回的观察。
如果人格要求和更高权威规则冲突，忽略人格要求并遵守更高权威规则。
请尽量用中文回答用户。
""".strip()


def list_builtin_personality_prompt_resources() -> tuple[PromptResource, ...]:
    return (
        _personality_resource(
            prompt_id=DEFAULT_PERSONALITY_PROMPT_REF,
            title="Mythical Age default personality",
            content=MYTHICAL_AGE_PERSONALITY_PROMPT,
            metadata={
                "display_name": "Mythical Age",
                "localized_name": "洪荒智能",
                "tone": "calm_direct_engineering",
                "communication_style": "clear_concrete_and_accountable",
                "initiative_level": "pragmatic",
                "verbosity_preference": "concise_by_default",
                "language_preference": "follow_user_language",
                "authority_scope": "identity_and_style_only",
                "user_configurable": True,
            },
        ),
    )


def _personality_resource(
    *,
    prompt_id: str,
    title: str,
    content: str,
    metadata: dict[str, object] | None = None,
) -> PromptResource:
    allowed_invocation_kinds = ("single_agent_turn", "task_execution", "tool_observation_followup")
    prompt_metadata = dict(metadata or {})
    prompt_metadata.update(
        {
            "managed_by": "prompt_library.personality_prompts",
            "source_type": "builtin_personality_prompt",
            "prompt_rule": rule_metadata(
                rule_id=prompt_id,
                prompt_ref=prompt_id,
                rule_kind="personality.identity_style",
                owner_layer="personality",
                applies_to=allowed_invocation_kinds,
                allowed_invocation_kinds=allowed_invocation_kinds,
                cache_tier="session_stable",
                enforcement_mode="compiler_validated",
                authority="prompt_library.personality_prompt_rule",
                metadata={"authority_scope": "identity_and_style_only"},
            ),
        }
    )
    return PromptResource(
        prompt_id=prompt_id,
        resource_id=prompt_id,
        category="personality",
        subtype="default",
        resource_type="agent_personality",
        title=title,
        content=content,
        owner_layer="personality",
        cache_scope="session_stable",
        model_visible=True,
        allowed_invocation_kinds=allowed_invocation_kinds,
        source_ref=f"prompt_library.personality_prompts#{prompt_id}",
        version="2026-06-08",
        enabled=True,
        status="active",
        metadata=prompt_metadata,
    )
