<skills>
  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>
  <skill name="网页操作">
    <description>让主 Agent 使用受控浏览器打开网页、观察页面、点击、输入、等待、截图和抽取内容。</description>
    <output_rule>直接完成用户可见任务；不要描述内部工具调用、路由策略或协议。</output_rule>
  </skill>
  <skill name="深度网络研究">
    <description>用于跨来源深度网络研究，要求建立研究合同、分面搜索、阅读关键原文、交叉验证证据，并输出可信度、限制和可追溯来源。</description>
    <use_when>用户需要系统调研、技术路线比较、GitHub/论文/官方资料综合、竞品分析、证据交叉验证或高可信结论；问题不能只靠一次搜索摘要可靠回答。</use_when>
    <subagent_handoff_protocol>先建立研究合同和搜索面；用 web_search 扩展候选来源，用 fetch_url 阅读关键原文；范围较大且允许子 agent 时，可按论文、GitHub、官方资料、新闻公告拆分子任务并等待结构化结果。</subagent_handoff_protocol>
    <return_protocol>返回研究结论、证据表、来源质量判断、冲突点、可信度、限制和建议下一步；关键结论必须能追溯到来源。</return_protocol>
    <output_rule>先给结论和判断，再列证据；不要暴露内部工具名、路由名、skill_id 或未整理的搜索日志。</output_rule>
  </skill>
  <skill name="生图提示词设计">
    <description>用于角色立绘、场景图、封面图和视觉参考图生成。主 Agent 应在用户明确要求出图时，用它把意图整理成可执行的高质量提示词，并调用生图工具产出真实图片。</description>
    <use_when>用户明确要求真实出图、角色立绘、场景图、封面图、概念图、视觉参考图，或任务要求必须生成真实图片产物。用户只是讨论设定、风格、配色或视觉建议时，不要调用生图工具。</use_when>
    <return_protocol>调用成功后，返回真实图片结果和路径，不要只返回 prompt。调用失败时，说明失败原因，并保留用户原需求和整理后的 prompt，方便配置修复后重试。</return_protocol>
    <output_rule>设计并调用生图 prompt 时：
- prompt 按“主体和用途、关键外观、构图视角、背景环境、光线色彩、风格边界、质量约束、no text、no watermark”组织，不要只堆抽象风格词。
- 角色写清全身/半身、姿态、服装材质、表情和轮廓；场景写清地点、空间层次、前中后景、光源和视觉焦点；道具/图标写清单一主体、居中、简单背景和适合缩放。
- 默认工具参数：`size=1024x1024`、`quality=low`、`request_timeout_seconds=150`、`overwrite=false`。
- 游戏 sprite、tile、icon 等小尺寸交付物仍使用 `size=1024x1024`，再用 `output_size=128x128`、`256x256` 或 `512x512` 缩放。
- 默认不要填写 `model`，让工具使用后端统一生图配置；不要自行改成其他模型。
- 不要在 prompt 中写 64x64、128x128、tiny、8-bit、transparent background、内部任务名或系统说明。
- 如果工具返回 `agent_retry_policy=do_not_auto_retry`，不要继续换 prompt 或换模型硬试；应报告配置/供应商阻塞。</output_rule>
  </skill>
  <skill name="PDF 阅读分析">
    <description>用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。</description>
    <output_rule>直接完成用户可见任务；不要描述内部工具调用、路由策略或协议。</output_rule>
  </skill>
  <skill name="知识库问答">
    <description>面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。</description>
    <output_rule>直接完成用户可见任务；不要描述内部工具调用、路由策略或协议。</output_rule>
  </skill>
  <skill name="Skill 创建顾问">
    <description>用于创建、改写和审查能力系统 Skill，帮助把用户意图整理成清晰的能力边界、触发条件、执行准则和模型可见提示。</description>
    <use_when>当用户要新增、改写、审查或拆分 Skill 时使用；重点处理能力边界、触发条件、依赖 operation、正文是否面向 Agent 执行、以及输出协议是否稳定。</use_when>
    <return_protocol>返回 Skill 草案或审查意见时，分清 metadata、prompt/body、requires_operations、requires_capabilities、适用场景、不适用场景、验证缺口；如果能力过宽，直接给出拆分建议。</return_protocol>
    <output_rule>先给可执行结论，再给需要修改的具体字段和正文片段；不要把 Skill 写成开发说明，不要编造不存在的工具或权限。</output_rule>
  </skill>
  <skill name="结构化数据分析">
    <description>用于本地 Excel、CSV、JSON 等结构化数据的可计算分析，适合筛选、排序、分组汇总、Top N、极值记录和结构检查。</description>
    <output_rule>直接完成用户可见任务；不要描述内部工具调用、路由策略或协议。</output_rule>
  </skill>
  <skill name="工程化 Debug">
    <description>工程化 Debug 技能。用于软件故障、回归、测试失败、状态异常、接口异常、页面异常、异步链路和自动化执行异常；要求先还原应然链路，再用运行时事实定位第一处偏离，修复结构根因并复测闭环。</description>
    <output_rule>直接完成用户可见任务；不要描述内部工具调用、路由策略或协议。</output_rule>
  </skill>
  <skill name="视觉资产生成">
    <description>在任务合同或用户请求需要真实图片交付物时，指导 agent 调用 image_generate 生成可验收的视觉资产，并把工具返回的真实路径作为交付证据。</description>
    <use_when>用户明确要求真实图片、任务合同要求图片产物，或开发/创作任务明确需要角色、怪物、场景、道具、封面、UI 图标等真实视觉资产。没有明确图片需求时，不要主动把文本或代码任务改成生图任务。</use_when>
    <return_protocol>成功后必须返回工具产出的真实 `image.src`、`image.file_path` 或 artifact 引用；失败时必须报告结构化错误和可重试 prompt，不能伪造图片路径，也不能用 CSS、emoji、占位图或外链图片冒充真实生成结果。</return_protocol>
    <output_rule>执行真实视觉资产生成时：
- 先判断是否真的需要图片；需要多张图时先生成最关键的 1-2 张，除非合同明确要求更多。
- 默认使用低成本稳定配置：`size=1024x1024`、`quality=low`、`request_timeout_seconds=150`；最低配置任务可用 120 秒。
- 小图不要把 128x128/256x256 直接作为 API `size`；保持 `size=1024x1024`，用 `output_size=128x128`、`256x256` 或 `512x512` 做本地缩放。
- 角色/怪物用 `asset_kind=character`，场景/背景用 `asset_kind=scene`，道具/图标/封面或通用图用 `asset_kind=chat`。
- `target_id` 必须短、稳定、语义清楚；`overwrite` 默认 false；`model` 默认不要填写，让工具使用后端统一生图配置。
- prompt 必须包含主体、用途、构图/视角、环境、风格、色彩、质量边界，并明确 no text、no watermark。
- 像素风写 `clean pixel-art inspired 2D game asset, crisp silhouette, simple background`；不要写 tiny、8-bit、transparent background 或内部任务说明。
- 如果工具返回 `agent_retry_policy=do_not_auto_retry`，不要继续换 prompt 或换模型硬试；应报告配置/供应商阻塞。</output_rule>
  </skill>
  <skill name="快速网络简报">
    <description>用于快速搜索当前网络信息并给出简短、有来源链接的简报，适合新闻、官网状态、当前事实和轻量资料确认。</description>
    <use_when>用户需要快速了解当前网络信息、最近新闻、官网状态、发布动态或少量来源链接；任务目标明确，通常不需要跨来源深度论证。</use_when>
    <subagent_handoff_protocol>先用 web_search 获取候选来源；只有关键日期、版本、声明或结论需要确认时才使用 fetch_url 阅读原文；不要启动长任务，除非用户明确要求持续研究或产出文件。</subagent_handoff_protocol>
    <return_protocol>返回结论、来源链接、日期或更新时间、简短影响说明和无法确认的限制；链接必须来自实际搜索或抓取结果。</return_protocol>
    <output_rule>简短直接，先给结果；不要暴露内部工具名、路由名、skill_id 或搜索过程日志。</output_rule>
  </skill>
</skills>
