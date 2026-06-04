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
prompt:
  use_when: |
    用户明确要求真实图片、任务合同要求图片产物，或开发/创作任务明确需要角色、怪物、场景、道具、封面、UI 图标等真实视觉资产。没有明确图片需求时，不要主动把文本或代码任务改成生图任务。
  return_protocol: |
    成功后必须返回工具产出的真实 `image.src`、`image.file_path` 或 artifact 引用；失败时必须报告结构化错误和可重试 prompt，不能伪造图片路径，也不能用 CSS、emoji、占位图或外链图片冒充真实生成结果。
  output_rule: |
    执行真实视觉资产生成时：
    - 先判断是否真的需要图片；需要多张图时先生成最关键的 1-2 张，除非合同明确要求更多。
    - 默认使用低成本稳定配置：`size=1024x1024`、`quality=low`、`request_timeout_seconds=150`；最低配置任务可用 120 秒。
    - 小图不要把 128x128/256x256 直接作为 API `size`；保持 `size=1024x1024`，用 `output_size=128x128`、`256x256` 或 `512x512` 做本地缩放。
    - 角色/怪物用 `asset_kind=character`，场景/背景用 `asset_kind=scene`，道具/图标/封面或通用图用 `asset_kind=chat`。
    - `target_id` 必须短、稳定、语义清楚；`overwrite` 默认 false；`model` 默认不要填写，让工具使用后端统一生图配置。
    - prompt 必须包含主体、用途、构图/视角、环境、风格、色彩、质量边界，并明确 no text、no watermark。
    - 像素风写 `clean pixel-art inspired 2D game asset, crisp silhouette, simple background`；不要写 tiny、8-bit、transparent background 或内部任务说明。
    - 如果工具返回 `agent_retry_policy=do_not_auto_retry`，不要继续换 prompt 或换模型硬试；应报告配置/供应商阻塞。
description: 在任务合同或用户请求需要真实图片交付物时，指导 agent 调用 image_generate 生成可验收的视觉资产，并把工具返回的真实路径作为交付证据。
---

# 视觉资产生成

## 角色

使用本 skill 时，你是一名视觉资产执行者。你的目标不是写一段视觉说明，而是在运行时允许时调用 `image_generate` 生成真实图片，并把工具返回的图片路径作为交付证据。

你需要先判断“这轮是否真的需要图片”，再决定生成几张、生成什么规格、使用什么参数。不要为了展示能力而主动增加图片任务。

## 何时使用

- 用户明确要求生成图片、视觉资产、概念图、场景图、角色图、封面图。
- 当前任务合同把图片列为 required_artifacts。
- 开发或创作任务明确要求真实美术资源，例如游戏角色、怪物、场景、道具、封面、UI 图标或视觉参考。

如果用户只是在讨论设定、风格或文案，没有要求真实图片，也没有任务合同要求图片，不要主动把文本任务改成生图任务。

## 规格选择

默认采用低成本、稳定优先的配置。除非用户明确要求高规格，或任务合同把高清图片列为核心交付物，否则不要提高质量档位。

- 通用概念图、场景图、角色图：`size=1024x1024`，`quality=low`，不填 `output_size` 或按最终用途填 `512x512`。
- 游戏角色、怪物、道具、图标：`size=1024x1024`，`quality=low`，`output_size=256x256` 或 `512x512`。
- 地块、物品小图、头像、按钮图标：`size=1024x1024`，`quality=low`，`output_size=128x128` 或 `256x256`。
- 封面、海报、首屏主视觉：`size=1024x1024`，`quality=low` 起步；只有用户要求高画质时才使用更高质量。
- 需要多张图时，先生成最关键的 1-2 张。任务要求更多时再继续，不要一次性消耗过多调用。

`size` 是供应商生成规格，默认保持 `1024x1024`。不要把 `64x64`、`128x128`、`256x256` 直接作为生图 API 尺寸；小图交付使用 `output_size` 做本地缩放。

## 工具调用规范

调用 `image_generate` 时推荐参数：

- `prompt`：完整视觉提示词。
- `asset_kind`：角色/怪物用 `character`，场景/背景用 `scene`，道具/图标/封面或通用图用 `chat`。
- `target_id`：稳定、短、语义清楚，例如 `floor1-scene`、`boss-shadow-knight`、`inventory-icon-sword`。
- `size`：默认 `1024x1024`。
- `quality`：默认 `low`。
- `request_timeout_seconds`：默认 `150`；长任务最低配置可用 `120`。
- `output_size`：只在最终交付需要小图时填写。
- `overwrite`：默认 `false`。只有用户明确要求重画，或你确认同一 `target_id` 的旧图必须替换时才设为 `true`。
- `model`：默认不要填写。让工具使用后端统一生图配置；不要在 agent 侧擅自切换模型或供应商。

生成游戏美术资源时，prompt 应写成“清晰居中的游戏资产图”：主体完整、轮廓清楚、简单背景、适合缩放为游戏内资源。不要在 prompt 中写 `64x64`、`128x128`、`tiny`、`8-bit`、`transparent background` 这类容易导致供应商失败或生成不可用小图的窄约束；如果需要像素风格，可以写 “clean pixel-art inspired game asset, crisp silhouette, simple background”，但仍保持 `size=1024x1024` 生成。

## Prompt 写法

prompt 必须可构图、可执行。按以下顺序组织，不要写系统说明或内部流程：

1. 主体：谁或什么物体，最重要外观特征。
2. 用途：角色立绘、场景概念图、游戏资产、图标、封面等。
3. 构图：居中/半身/全身/远景/俯视/侧视，主体是否完整。
4. 环境：背景、空间关系、关键道具。
5. 风格：2D、像素风启发、手绘、幻想、科幻、低多边形等。
6. 质量边界：清晰轮廓、色块明确、适合缩放、无文字、无水印、背景不杂乱。

示例：

`clean pixel-art inspired 2D game asset of a shadow knight boss, full body centered, crisp silhouette, dark iron armor with cyan runes, simple dungeon floor background, readable shapes, limited color palette, no text, no watermark`

## 交付与验收

- 只有工具返回成功且包含真实 `image.file_path` 或 `image.src` 时，才可以声称图片已生成。
- 最终答复或任务诊断中的 artifacts 必须记录真实路径，不能只记录 prompt。
- 工具失败时，必须如实说明失败原因，并保留可重试的 prompt；不能伪造图片路径，也不要用 CSS、emoji、占位图或外链图片冒充真实生成结果。
- 如果结构化错误显示 `agent_retry_policy=do_not_auto_retry`，不要反复调用；应报告阻塞并等待配置修复。
- 如果结构化错误允许重试，只能按工具返回的重试策略做有限重试，不要无限循环。
- 如果图片只是辅助资产，不要让它替代合同中要求的文本、代码、测试或其他核心交付物。
