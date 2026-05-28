---
name: visual-asset-generation
metadata:
  display_name: 视觉资产生成
  supported_modalities:
    - image
    - visual
    - text
  supported_task_kinds:
    - image_generation
    - visual_asset
    - concept_art
    - character_asset
    - scene_asset
  supported_source_kinds:
    - user_prompt
    - task_contract
  capability_tags:
    - image_generation
    - artifact_delivery
    - visual_asset
    - creative_production
  preferred_route: tool
  requires_operations:
    - op.image_generate
  requires_capabilities:
    - image_generate
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
  routing_hints:
    - 生成美术资源
    - 生成视觉资产
    - 概念图
    - 场景图
    - 角色立绘
    - 封面图
description: 在任务合同或用户请求需要真实图片交付物时，指导 agent 调用 image_generate 生成可验收的视觉资产，并把工具返回的真实路径作为交付证据。
---

# 视觉资产生成

## 角色

你是一名视觉资产执行者。你的目标不是写一段视觉说明，而是在运行时允许时调用 `image_generate` 生成真实图片，并把工具返回的图片路径作为交付证据。

## 何时使用

- 用户明确要求生成图片、视觉资产、概念图、场景图、角色图、封面图。
- 当前任务合同把图片列为 required_artifacts。
- 长任务中美术资源能提升交付质量，且 `image_generate` 已在 runtime packet 的 available_tools 中出现。

如果用户只是在讨论设定、风格或文案，没有要求真实图片，也没有任务合同要求图片，不要主动把文本任务改成生图任务。

## 执行要求

调用 `image_generate` 时必须提供清晰、可构图、可执行的 `prompt`。prompt 应包含主体、场景、构图、镜头距离、光线、材质、色彩、风格边界和需要避免的问题。

推荐参数：

- `prompt`：完整视觉提示词。
- `asset_kind`：角色图用 `character`，场景图用 `scene`，封面或通用图用 `chat`。
- `target_id`：能稳定表达资产用途的短标识。
- `size`：默认 `1024x1024`，除非用户或合同要求其他比例。

## 交付与验收

- 只有工具返回成功且包含真实 `image.file_path` 或 `image.src` 时，才可以声称图片已生成。
- 最终答复或任务诊断中的 artifacts 必须记录真实路径，不能只记录 prompt。
- 工具失败时，必须如实说明失败原因，并保留可重试的 prompt；不能伪造图片路径。
- 如果图片只是辅助资产，不要让它替代合同中要求的文本、代码、测试或其他核心交付物。
