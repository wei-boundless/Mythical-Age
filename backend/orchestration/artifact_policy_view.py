from __future__ import annotations

from typing import Any


def artifact_policy_summary(policy: dict[str, Any] | None) -> dict[str, Any]:
    artifact_policy = dict(policy or {})
    artifacts = [
        dict(item)
        for item in list(artifact_policy.get("artifacts") or [])
        if isinstance(item, dict)
    ]
    if not artifacts:
        target = str(
            artifact_policy.get("artifact_target")
            or artifact_policy.get("output_path")
            or ""
        ).strip()
        if target:
            artifacts = [
                {
                    "path": target,
                    "required": bool(artifact_policy.get("required", True)),
                    "content_source": "final_content",
                    "fallback_to_full_content": True,
                }
            ]
    paths = [
        str(item.get("path") or item.get("naming_rule") or "").strip()
        for item in artifacts
        if str(item.get("path") or item.get("naming_rule") or "").strip()
    ]
    return {
        "enabled": bool(artifact_policy.get("enabled") or paths),
        "required": bool(artifact_policy.get("required", bool(paths))),
        "default_artifact_root": str(
            artifact_policy.get("artifact_root")
            or artifact_policy.get("default_artifact_root")
            or ""
        ).strip(),
        "subdir_template": str(artifact_policy.get("subdir_template") or "").strip(),
        "artifact_count": len(paths),
        "target_paths": paths,
        "content_sources": sorted(
            {
                str(item.get("content_source") or "final_content").strip()
                for item in artifacts
                if str(item.get("content_source") or "final_content").strip()
            }
        ),
        "fallback_to_full_content": any(bool(item.get("fallback_to_full_content")) for item in artifacts),
        "source": str(artifact_policy.get("source") or "").strip(),
        "runtime_rule": "required_final_content_materialized_to_configured_files",
        "debug_reports_are_not_deliverables": True,
    }


def render_artifact_policy_instructions(
    policy: dict[str, Any] | None,
    *,
    heading: str = "产物政策",
) -> str:
    summary = artifact_policy_summary(policy)
    if not summary["enabled"]:
        return ""
    lines = [f"{heading}："]
    requirement = "必须产出正式文本产物" if summary["required"] else "允许产出正式文本产物"
    lines.append(f"- 要求：{requirement}；最终产物内容会按产物政策落盘，不能只写状态说明或执行说明。")
    if summary["target_paths"]:
        lines.append("- 正式产物路径：" + "、".join(summary["target_paths"]) + "。")
    if summary["default_artifact_root"]:
        root = summary["default_artifact_root"]
        subdir = str(summary.get("subdir_template") or "").strip()
        lines.append(f"- 产物根目录：{root}" + (f"；运行子目录模板：{subdir}。" if subdir else "。"))
    if summary["content_sources"]:
        lines.append("- 内容来源：" + "、".join(summary["content_sources"]) + "。")
    if summary["fallback_to_full_content"]:
        lines.append("- 若没有可拆分单元，系统会用完整最终产物内容写入目标文件；因此最终产物内容必须就是可验收的完整产物。")
    lines.append("- 调试报告、运行说明、占位文本不算正式交付产物。")
    return "\n".join(lines)
