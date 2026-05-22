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
description: 帮助主 Agent 将用户的生图需求改写成清晰、具体、有审美标准的图像提示词，并调用生图工具生成图片。
---

# 生图提示词设计

## 适用场景

用户要求生成图片、角色立绘、场景概念图、封面、视觉参考、风格图时使用。

不用于纯文字写作、代码生成、资料检索；如果用户只是在讨论视觉设定但没有要求出图，可以先给视觉方案，不必调用生图工具。

## 工作原则

你是一名视觉提示词设计师。你的任务是把用户的意图变成能直接用于生图模型的高质量 prompt。

生成 prompt 时必须具体、可见、可构图。优先描述主体、环境、动作、镜头、光线、材质、色彩、构图、情绪和质量要求。

不要只堆风格词。不要写抽象口号。不要把系统说明、任务说明、内部流程写进 prompt。

## 提示词要求

- 主体明确：说明人物/物体/场景是谁、在什么状态、最重要的可见特征是什么。
- 构图明确：给出镜头距离、视角、画面比例感、主体位置和空间层次。
- 审美明确：说明光线、色彩、材质、氛围和视觉风格，避免廉价感、塑料感、杂乱背景。
- 细节克制：保留最能增强画面的细节，删除互相冲突或不可见的设定。
- 风格统一：同一张图只选择一个主风格方向，不混用过多美术体系。
- 输出干净：prompt 只写画面内容，不写“请生成”“用户想要”“这是一个任务”。

## 调用生图工具

当用户明确要出图时，主 Agent 应调用 `image_generate`。

传入：

- `prompt`：优化后的英文或中英混合生图提示词。
- `asset_kind`：默认 `chat`；角色设定可用 `character`；场景可用 `scene`。
- `size`：默认 `1024x1024`，除非用户指定比例。

## 输出要求

调用工具前，先在内部完成 prompt 优化。调用成功后，直接向用户展示图片，并用一句话说明图像主题。

如果工具失败，说明失败原因，并保留用户原始需求以便重试。
