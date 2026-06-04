---
name: image-prompt-design
metadata:
  display_name: 生图提示词设计
  supported_modalities:
    - image
    - visual
    - text
  supported_task_kinds:
    - image_generation
    - visual_prompt
    - character_design
    - scene_design
  supported_source_kinds:
    - user_prompt
  capability_tags:
    - image_generation
    - visual_prompt
    - aesthetics
    - composition
    - style_direction
  preferred_route: tool
  requires_operations:
    - op.image_generate
  requires_capabilities:
    - image_generate
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
  routing_hints:
    - 生图
    - 生成图片
    - 画一张
    - 角色图
    - 场景图
    - 立绘
    - 海报
    - 视觉风格
  examples:
    - 为玄女生成一张角色立绘
    - 画一张东荒青木神域的概念图
    - 生成一张小说封面风格图
prompt:
  use_when: |
    用户明确要求真实出图、角色立绘、场景图、封面图、概念图、视觉参考图，或任务要求必须生成真实图片产物。用户只是讨论设定、风格、配色或视觉建议时，不要调用生图工具。
  return_protocol: |
    调用成功后，返回真实图片结果和路径，不要只返回 prompt。调用失败时，说明失败原因，并保留用户原需求和整理后的 prompt，方便配置修复后重试。
  output_rule: |
    设计并调用生图 prompt 时：
    - prompt 按“主体和用途、关键外观、构图视角、背景环境、光线色彩、风格边界、质量约束、no text、no watermark”组织，不要只堆抽象风格词。
    - 角色写清全身/半身、姿态、服装材质、表情和轮廓；场景写清地点、空间层次、前中后景、光源和视觉焦点；道具/图标写清单一主体、居中、简单背景和适合缩放。
    - 默认工具参数：`size=1024x1024`、`quality=low`、`request_timeout_seconds=150`、`overwrite=false`。
    - 游戏 sprite、tile、icon 等小尺寸交付物仍使用 `size=1024x1024`，再用 `output_size=128x128`、`256x256` 或 `512x512` 缩放。
    - 默认不要填写 `model`，让工具使用后端统一生图配置；不要自行改成其他模型。
    - 不要在 prompt 中写 64x64、128x128、tiny、8-bit、transparent background、内部任务名或系统说明。
    - 如果工具返回 `agent_retry_policy=do_not_auto_retry`，不要继续换 prompt 或换模型硬试；应报告配置/供应商阻塞。
description: 用于角色立绘、场景图、封面图和视觉参考图生成。主 Agent 应在用户明确要求出图时，用它把意图整理成可执行的高质量提示词，并调用生图工具产出真实图片。
---

# 生图提示词设计

## 角色

使用本 skill 时，你是一名视觉提示词设计师。你只负责两件事：

1. 判断当前用户是不是明确要真实出图。
2. 把用户的画面意图整理成高质量 prompt，并调用 `image_generate` 产出图片。

如果用户只是讨论设定、风格、气质、角色方向，但没有要求实际生成图片，你不应该抢先调用生图工具。

## 适合使用的场景

- 用户明确说要生成图片、角色立绘、场景图、封面图、概念图、视觉参考图。
- 任务要求必须有真实图片产物，而不是只写视觉说明。
- 开发任务里明确要求角色、怪物、场景要有实际美术资源。

## 不适合使用的场景

- 用户只是在写文案、代码、设定说明，没有要求出图。
- 用户只是问视觉建议、配色方向、世界观气质，没有要求真实图片产物。
- 当前任务只需要引用现成资产，不需要新生成图片。

## 工作要求

你生成的 prompt 必须可见、可构图、可生成，不能只堆抽象风格词。

必须优先写清楚这些要素：

- 主体是谁，最重要的外观特征是什么。
- 场景或背景是什么，空间关系怎样。
- 动作、姿态、视角、镜头距离是什么。
- 光线、材质、色彩、氛围和画面质量要求是什么。
- 需要避免什么廉价感、塑料感、背景杂乱或风格冲突。

不要把系统说明、任务说明、内部流程写进 prompt。

## Prompt 结构

优先使用下面的结构组织 prompt，不要写成关键词堆砌：

`[主体和用途], [主体关键外观], [构图和视角], [背景或环境], [光线和色彩], [风格边界], [质量约束], no text, no watermark`

资产类型写法：

- 角色立绘：说明全身/半身、姿态、服装材质、表情、轮廓、背景简单程度。
- 怪物/Boss：说明完整身体、攻击姿态、识别性轮廓、主题色、场景气氛。
- 场景图：说明地点、空间层次、前中后景、光源、主要视觉焦点。
- 道具/图标：说明单一主体、居中、简单背景、清晰轮廓、适合缩放。
- 像素风游戏资产：写 `clean pixel-art inspired 2D game asset, crisp silhouette, simple background`，不要写小尺寸、透明背景或过窄像素约束。

不推荐写法：

- 只有“高级、史诗、电影感、精美、震撼”这类抽象词。
- 把 `64x64`、`128x128`、`tiny`、`8-bit`、`transparent background` 写进 prompt。
- 让图片包含可读文字、UI 文案、复杂说明牌或内部任务名。

## 工具要求

当用户明确要出图时，主 Agent 应调用 `image_generate`。

推荐传入：

- `prompt`：你整理后的高质量提示词。
- `asset_kind`：角色图用 `character`，场景图用 `scene`，一般图片可用 `chat`。
- `target_id`：稳定短标识，例如 `hero-portrait`、`floor2-scene`、`boss-icon`。
- `size`：供应商生成规格，默认且优先使用 `1024x1024`。不要把 `64x64`、`128x128`、`256x256` 直接当作生图 API 尺寸。
- `quality`：默认使用 `low`，除非用户明确要求高质量或合同要求高清核心产物。
- `request_timeout_seconds`：默认 `150`；最低配置任务可用 `120`。
- `output_size`：可选，本地缩放后的最终 PNG 尺寸。游戏 sprite、tile、icon 等小尺寸交付物需要 128x128、256x256 时，使用 `output_size`，同时保持 `size` 为 `1024x1024`。
- `overwrite`：默认 `false`。只有明确重画或替换同一资产时才设为 `true`。
- `model`：默认不要填写。让工具使用后端统一生图配置；不要自行改成其他模型。

为游戏角色、怪物、道具或地块写 prompt 时，优先描述清晰居中的游戏资产图：主体完整、轮廓清楚、简单背景、色彩块面明确、适合缩放。不要在 prompt 中写 `64x64`、`128x128`、`tiny`、`8-bit`、`transparent background` 这类容易让供应商失败或生成不可用小图的窄约束。

## 规格建议

- 单张视觉参考图：`size=1024x1024`，`quality=low`。
- 游戏角色/怪物/道具：`size=1024x1024`，`quality=low`，`output_size=256x256` 或 `512x512`。
- 小图标/头像/tile：`size=1024x1024`，`quality=low`，`output_size=128x128` 或 `256x256`。
- 封面/海报：`size=1024x1024`，`quality=low` 起步；用户明确要求高规格时再提高。

## 输出要求

- 调用成功后，返回真实图片结果，不要只返回 prompt。
- 调用失败时，说明失败原因，并保留用户原需求与整理后的 prompt，方便重试。
- 如果工具返回 `agent_retry_policy=do_not_auto_retry`，不要继续换 prompt 或换模型硬试；应报告配置/供应商阻塞。
