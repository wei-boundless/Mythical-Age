# Agent 工具调用语义契约重构计划书

日期：2026-06-27

## 1. 问题结论

当前问题不是 agent 不会使用工具，也不是工具权限本身被关闭，而是工具调用契约没有为 agent 铺出一条自然、稳定、可执行的主链。

本次问题暴露出三类结构性缺陷：

1. Agent 可见提示混入了工程侧术语，例如 `JSON action`、`tool channel`、`provider-native`、`closeout`、`runtime`、`修复通道` 等。这些词对工程有意义，但会污染 agent 的语义空间。
2. Agent 的公开判断和工具动作承载没有被设计成同一个自然工作面。结果是 agent 想先说明判断依据时，系统容易把它当成普通正文；agent 想继续调用工具时，又缺少足够清晰的行动表达模板。
3. 输出门禁、动作解析、工具准入和收口反馈没有形成同一条主链。工具意图没有进入执行时，反馈不应该把问题推给 agent，更不应该诱导 agent 说“工具通道关闭”或“上一轮已经搜索”。

因此，重构重点不是限制 agent，而是清理错误引导、统一契约、让系统服务 agent 的判断和调度。

## 2. 目标原则

### 2.1 Agent 权责

Agent 是语义判断与行动调度主体。

Agent 应被明确告知：

- 你需要先判断用户目标、已知事实、缺失事实和下一步行动。
- 当需要查证、读取、搜索、执行或验证时，你可以先给用户一个简短的公开判断，再提出本次需要使用的工具。
- 你的公开判断必须诚实反映当前状态：没有工具结果时，不能说已经查到、已经搜索、已经验证。
- 工具结果返回后，你根据观察继续判断：继续查证、询问用户、说明阻塞或给出最终回答。

### 2.2 系统权责

系统只负责承载、授权、执行、记录和回填观察。

系统不负责：

- 替 agent 判断目标。
- 替 agent 改写行动意图。
- 用“格式错误”压制 agent 的表达。
- 在没有真实工具观察时制造“已执行”语义。
- 用 closeout、tool channel、provider-native 等工程词汇教育 agent。

### 2.3 Prompt 语言边界

工程内部可以使用 `runtime`、`parser`、`admission`、`provider-native`、`JSON action` 等术语。

Agent 可见 prompt 不使用这些开发语义，除非字段名本身是必须填写的动作承载格式。

禁止出现在 agent 可见语义中的表达：

- “系统会接住你的工具意图”
- “伪工具块”
- “修复通道”
- “tool channel / 工具通道”
- “provider-native”
- “sidecar”
- “closeout”
- “runtime 节点”
- “这是事实边界”
- “开发前缀 / 动态尾 / 静态前缀”

允许出现在 agent 可见语义中的表达：

- “当前可用工具”
- “本次需要查证的事实”
- “本次行动”
- “公开判断”
- “下一步”
- “工具返回的观察”
- “尚未完成 / 尚未查证 / 尚未执行”

## 3. 目标主链

目标链路：

```text
用户请求
-> 上下文与工具清单进入 agent 语义空间
-> agent 形成公开判断和下一步行动
-> 行动承载层读取 agent 的工具请求
-> 工具准入与执行
-> 工具观察回填给 agent
-> agent 继续判断或收口
```

其中：

- 公开判断是 agent 的表达权，不是噪声。
- 工具请求是 agent 的行动权，不是系统猜测。
- 系统反馈只报告行动是否执行、观察是什么、缺少什么条件。

## 4. Agent 可见动作承载设计

### 4.1 工具调用前的表达

Agent 可以先表达：

- 为什么当前问题需要查证。
- 已知事实是什么。
- 未确认事实是什么。
- 本次工具行动要解决什么判断目标。

这些内容进入公开语义字段，例如：

```json
{
  "public_progress_note": "这个问题涉及实时价格，我需要先查证当前公开报价后再比较。",
  "public_action_state": {
    "current_judgment": "已有知识不足以可靠判断最新价格。",
    "next_action": "查询当前多模态模型 API 价格。"
  }
}
```

这不是限制 agent，而是给 agent 一个稳定的公开表达位置。

### 4.2 工具调用的可执行承载

工具请求只表达工具名和参数。

示例：

```json
{
  "authority": "harness.loop.model_action_request",
  "action_type": "tool_call",
  "public_progress_note": "这个问题涉及实时价格，我需要先查证当前公开报价后再比较。",
  "public_action_state": {
    "current_judgment": "已有知识不足以可靠判断最新价格。",
    "next_action": "查询当前多模态模型 API 价格。",
    "completion_status": "waiting_for_tool"
  },
  "tool_calls": [
    {
      "tool_name": "web_search",
      "args": {
        "query": "2026 cheap multimodal LLM API pricing alternatives to DeepSeek"
      }
    }
  ]
}
```

工程内部可以要求对象结构，但 agent 可见说明必须强调它是在表达“本次行动”，不是在满足系统格式。

### 4.3 工具名引导

工具清单必须清楚告诉 agent：

- 当前可用工具名是什么。
- 每个工具适合什么语义任务。
- 工具名必须使用清单中的精确名称。

例如对搜索工具的 agent 可见说明应是：

```text
当问题依赖当前网页信息、价格、新闻、官方公告或需要来源核验时，使用 web_search。
```

不要写成：

```text
使用 web、search、provider tool 或 native tool。
```

## 5. 需要修改的代码范围

### 5.1 `backend/harness/runtime/compiler.py`

目标：

- 重写单 turn 动作合同的 agent 可见文案。
- 去掉容易污染语义的开发词。
- 明确“公开判断 + 下一步行动 + 工具请求”属于同一工作面。
- 强化可见工具名索引，尤其 `web_search`。

需要检查和修改的位置：

- 动作合同组装区域。
- `public_progress_note`、`public_action_state` 的说明。
- `tool_call` / `tool_calls[]` 的说明。
- `assistant_message_or_action` 相关输出格式说明。
- 工具索引稳定段的工具名展示。

### 5.2 `backend/harness/loop/single_agent_turn.py`

目标：

- 将“工具意图未执行”作为行动承载问题处理，而不是直接进入无工具收口。
- 收口反馈不得诱导 agent 声称工具已经执行。
- 工具未执行时，保留 agent 的判断与目标，把事实回交给 agent 继续决策。

需要检查和修改的位置：

- `_single_agent_action_request_from_response`
- `_model_protocol_violation_control_signal`
- `_final_output_not_committable_control_signal`
- `_agent_authored_closeout_messages`
- `emit_agent_authored_closeout`
- final 阶段错误恢复中移除 `tool_call` 的逻辑

重点清理：

- 不能因为候选输出未提交，就把 `tool_call` 从 allowed actions 中移除。
- 不能把“未形成可保存自然回应”直接变成“不能再用工具”。
- 不能在没有 observation 的情况下给 closeout 提供“已执行”暗示。

### 5.3 `backend/runtime/model_gateway/model_response_protocol.py`

目标：

- 只做响应规范化和诊断，不替 agent 判断。
- 识别出文本中存在工具行动表达时，交给上层保持 agent 意图，而不是把它当普通最终答复。
- 不把 Markdown/YAML 叫作 agent 错误；工程内部只标记为“未进入可执行承载”。

Agent 可见反馈不使用“伪工具块”这个词。

### 5.4 `backend/prompt_library/rules.py`

目标：

- 把规则从“限制输出”改为“帮助 agent 表达判断并行动”。
- 明确公开判断、问题、阻塞、最终回答和工具请求各自的语义位置。
- 删除或改写“只输出一个动作对象”这类压缩 agent 表达的措辞。

### 5.5 `backend/prompt_library/utility_prompts.py`

目标：

- 修正 action repair / admission repair 的 agent 可见语言。
- 反馈应说“本次行动尚未执行，请保留判断并重新表达本次行动”，不要说“格式错了”“工具通道关闭”。
- 修复提示只服务 agent 的继续判断，不控制 agent 的思考。

## 6. 必须删除或改写的旧逻辑

以下旧逻辑不符合目标主链，不能以兼容为理由保留：

1. 将普通文本优先当作最终回答，再由输出门禁拦截的链路。
2. final 阶段恢复时无条件移除 `tool_call` 的链路。
3. `final_output_not_committable` 默认关闭工具动作的链路。
4. closeout 里让 agent 根据工程状态词生成用户回复的链路。
5. agent 可见 prompt 中出现 `tool channel`、`provider-native`、`sidecar`、`closeout` 等工程词的链路。

## 7. 2026-06-27 实施补充：JSON 调用与 native tool 同类切换

本次补齐目标：JSON action 与 provider-native tool 不再是两套工具世界，而是同一套 `tool_call` 语义契约的两种传输实现。

工程落点：

- `backend/harness/runtime/tool_transport_adapter.py`
  - 新增 `ToolTransportContract`。
  - `selected_transport=json_action` 时，工具提交方式为 `action_object`，不绑定 provider 工具 sidecar。
  - `selected_transport=provider_native` 时，工具提交方式为 `direct_tool_selection`，sidecar 由同一套 mounted tools 和 canonical schema 生成。
  - 两种模式共用同一批 `mounted_tool_names`、同一套 `canonical_provider_tool_input_schema` 和同一执行入口。
- `backend/harness/runtime/compiler.py`
  - packet diagnostics 挂载隐藏 `tool_transport_contract`。
  - agent 可见运行投影只展示语义提交方式：`action_object` 或 `direct_tool_selection`，不向 agent 暴露 provider/native/sidecar。
  - `_runtime_projection_instruction()` 按本轮提交方式生成工具行动说明，避免同时提示两套调用方法。
- `backend/harness/loop/single_agent_turn.py`
  - provider sidecar 派生改为走 `ToolTransportContract`。
  - JSON action 和直接工具选择最终都归一为 `ModelActionRequest(action_type="tool_call")` 后进入 admission/execution。
  - 动作诊断标记 `tool_call_submission=action_object/direct_tool_selection`，便于确认真实切换。
- `backend/harness/runtime/tool_catalog_manifest.py`
  - 稳定工具目录不再只给少数工具生成参数契约；所有 prompt-visible mounted tools 都生成统一 `tool_contract_summary`。
  - 工具摘要只描述“选择该工具并填写 args 对象”，不绑定某一种传输承载。
- `backend/capability_system/tools/native_tool_catalog.py`
  - 修正 `list_dir` 注册契约，补齐实现实际支持的 `path`、`max_entries`。
- `backend/capability_system/tools/registries/TOOLS_REGISTRY.json`
  - 同步 `list_dir` 注册表参数，避免 registry 与 native catalog 漂移。
- `backend/prompt_library/rules.py`、`backend/prompt_library/utility_prompts.py`
  - 工具调用提示改为“按本轮工具行动合同表达”，避免在 direct tool selection 模式下仍强拉回 JSON action。

验收口径：

- JSON 模式：`selected_transport=json_action`，`selected_tool_call_submission=action_object`，`json_action.enabled=true`，`provider_native.enabled=false`。
- native 模式：`selected_transport=provider_native`，`selected_tool_call_submission=direct_tool_selection`，`json_action.enabled=false`，`provider_native.enabled=true`。
- 两种模式下工具目录的 `tool_contract_summary` 必须来自同一套 mounted tool contract。
- 两种模式下工具请求最终都进入同一个 admission/execution 链，不允许保留并行旧执行链。
6. 工具清单中让 agent 猜工具别名的模糊引导。

## 7. 实施阶段

### 阶段一：语义契约清理

只修改 prompt 和动作合同文案。

完成标准：

- Agent 可见文本不再出现禁止词。
- 工具调用前的公开判断被描述为合法表达。
- 工具名说明清晰指向 `web_search` 等真实工具名。

### 阶段二：解析与门禁顺序修正

修改 single turn 解析顺序。

完成标准：

- 包含工具行动表达的输出不会先被当作最终回答提交。
- 工具行动未进入执行时，不直接进入无工具收口。
- `tool_call` 不会在普通恢复中被无条件移除。

### 阶段三：反馈与收口重写

修改未执行、未提交、收口反馈。

完成标准：

- 反馈只报告：行动尚未执行、原因、当前仍可采取的行动。
- 无工具观察时，agent 不会被诱导说“已经搜索”。
- closeout 只基于真实 observation、commit、用户上下文。

### 阶段四：真实运行验证

不新增测试文件。

验证方式：

1. `python -m py_compile` 检查修改文件。
2. 固定端口重启后端 `127.0.0.1:8003` 和前端 `127.0.0.1:3000`。
3. 用 CLI/API 发起真实 turn：
   - 用户请求当前价格搜索。
   - 检查 agent 是否给出公开判断并调用 `web_search`。
   - 检查工具 observation 是否保存。
4. 发起 follow-up：
   - 问“你刚才搜索了吗？”
   - 检查 agent 是否只基于真实 observation 回答。
5. 检查历史和 runtime events：
   - 不出现“工具通道已关闭”类误导。
   - 不出现无 observation 却声称已执行。

## 8. 验收标准

本次重构完成后，应满足：

- Agent 可以自然表达判断依据，不被系统当成违规噪声。
- Agent 使用工具时有清晰可执行承载，不需要猜系统暗语。
- 系统只执行 agent 的行动请求，不替 agent 规划。
- 工具未执行时，反馈不压制 agent，而是帮助 agent 保留判断继续行动。
- 搜索类请求能稳定走 `web_search`。
- follow-up 能基于真实工具历史回答。
- Agent 可见语义中不出现开发侧污染词。

## 9. 暂停点

这份计划书仅用于确认重构方向。

在用户确认前，不实施代码修改。
