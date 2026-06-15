# Prompt Library 体系技术报告

> 审查日期：2026-06-15
> 审查范围：`backend/prompt_library/` 目录下全部 15 个源文件
> 总代码量：约 213 KB

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [核心数据模型（models.py）](#2-核心数据模型modelspy)
3. [Prompt 注册表与持久化（registry.py）](#3-prompt-注册表与持久化registrypy)
4. [Prompt 组装管线（assembly.py）](#4-prompt-组装管线assemblypy)
5. [Manifest 与运行时投影（manifest.py）](#5-manifest-与运行时投影manifestpy)
6. [Prompt Pack 体系（packs.py）](#6-prompt-pack-体系packspy)
7. [结构分层](#7-结构分层)
8. [模块详解](#8-模块详解)
   - [8.1 系统基础提示（system_prompts.py）](#81-系统基础提示system_promptspy)
   - [8.2 Agent 工作角色提示（agent_prompts.py）](#82-agent-工作角色提示agent_promptspy)
   - [8.3 Worker 提示（worker_prompts.py）](#83-worker-提示worker_promptspy)
   - [8.4 人格提示（personality_prompts.py）](#84-人格提示personality_promptspy)
   - [8.5 环境生命周期提示（environment_lifecycle_prompts.py）](#85-环境生命周期提示environment_lifecycle_promptspy)
   - [8.6 工具提示（tool_prompts.py）](#86-工具提示tool_promptspy)
   - [8.7 实用工具提示（utility_prompts.py）](#87-实用工具提示utility_promptspy)
   - [8.8 IO 能力提示（io_capability_prompts.py）](#88-io-能力提示io_capability_promptspy)
9. [规则系统（rules.py）](#9-规则系统rulespy)
10. [关键数据流](#10-关键数据流)
11. [文件索引](#11-文件索引)
12. [技术细节汇总](#12-技术细节汇总)

---

## 1. 整体架构概览

Prompt Library 子系统是整个运行时的**提示词供应链**。它的职责不是存储提示词文本，而是**按调用形态（invocation_kind）组装、排序、去重、校验并提供给运行时上下文**。

```
┌────────────────────────────────────────────────────────────────────┐
│                        Prompt Library                              │
│                                                                    │
│  ┌─────────────────┐   ┌──────────────┐   ┌────────────────────┐  │
│  │   Registry       │──▶│  Assembly     │──▶│     Manifest       │  │
│  │  (注册表/CRUD)   │   │  (组装管线)    │   │  (运行时投影)       │  │
│  └─────────────────┘   └──────────────┘   └────────────────────┘  │
│         │                                                          │
│         ▼                                                          │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                  存储层                                       │   │
│  │  JSON 持久化 (prompt_resources.json / prompt_packs.json)     │   │
│  │  + 内置资源（Python 元组的编译时资源）                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  资源分类：                                                        │
│  system → runtime → tool → skill → agent → personality →          │
│  environment → lifecycle → project → contract                     │
└────────────────────────────────────────────────────────────────────┘
```

### 核心概念

- **PromptResource**: 一条提示词资源。包含 content、category、owner_layer、cache_scope、allowed_invocation_kinds 等元数据。
- **PromptPack**: 一组有序的 prompt_ref 引用。代表一个完整的提示词集合（如 single_agent_turn 的完整 prompt 栈）。
- **PromptSection**: 组装后的一个 section，包含最终内容和排序信息。
- **PromptAssemblyResult**: 一次组装的完整结果，包括 sections、rejected_refs、manifest。
- **RuntimePromptManifest**: 运行时可消费的轻量清单。

---

## 2. 核心数据模型（models.py）

`models.py`（~15.9 KB，408 行）定义了整个 prompt library 的数据模型层。

### 2.1 PromptResource（核心资源模型）

```python
@dataclass(frozen=True, slots=True)
class PromptResource:
    prompt_id: str           # 唯一的 prompt 标识
    category: str            # 分类：system/runtime/agent/personality/environment/skill/task/graph_node
    subtype: str             # 子类型
    owner_layer: str         # 所属层：system/runtime/agent/environment/personality
    content: str             # 提示词正文
    cache_scope: str         # 缓存范围：static/static_environment/session_stable/task_stable
    status: str              # active/deprecated/archived
    allowed_invocation_kinds: tuple    # 允许的调用形态列表
    allowed_agent_refs: tuple          # 允许的 agent 引用
    allowed_environment_refs: tuple    # 允许的环境引用
    resource_type: str                 # 资源类型：system.foundation/runtime.rule/work_role/tool_guidance 等
    model_visible: bool                # 是否对模型可见
    source_ref: str                    # 来源引用
    version: str                       # 版本
    enabled: bool                      # 是否启用
    metadata: dict                     # 元数据（包含 prompt_rule 规则声明）
```

**关键属性**：
- `active`（属性）：`enabled and status == "active"` —— 判断是否活跃
- `deprecated_for_new_runtime`（属性）：`status in {"deprecated", "archived"}` 或 `metadata.deprecated_for_new_runtime is True`

**__post_init__ 自动推导**：
- prompt_id 默认为 resource_id（反之亦然）
- resource_type 从 category.subtype 推导
- owner_layer 从 category 推导（system→system, runtime→runtime, agent→agent 等）

### 2.2 PromptPack（提示词包）

```python
@dataclass(frozen=True, slots=True)
class PromptPack:
    pack_id: str                          # 唯一标识
    invocation_kind: str                  # 调用形态
    ordered_prompt_refs: tuple[str, ...]  # 有序的 prompt 引用列表
    cache_scope: str = "static"
    status: str = "active"
    allowed_agent_refs: tuple             # 允许的 agent
    allowed_environment_refs: tuple       # 允许的环境
```

Pack 的作用是为一类 invocation_kind 定义完整的提示词栈顺序。例如 `single_agent_turn` 需要加载 foundation prompts → runtime rule → 工具规则等。

### 2.3 PromptSection（组装后的片段）

```python
@dataclass(frozen=True, slots=True)
class PromptSection:
    section_id: str       # 格式："{category}.{subtype}:{order}"
    prompt_ref: str       # 原始的 prompt 引用
    category: str
    subtype: str
    title: str
    content: str          # 最终正文
    owner_layer: str
    cache_scope: str
    source_ref: str
    order: int
    metadata: dict
```

### 2.4 PromptRule（规则声明）

```python
@dataclass(frozen=True, slots=True)
class PromptRule:
    rule_id: str
    prompt_ref: str
    rule_kind: str              # 规则种类：system.foundation/runtime.protocol/runtime.instruction 等
    owner_layer: str
    applies_to: tuple           # 适用范围
    cache_tier: str             # 缓存层级：global_static/static_environment/session_stable/task_stable/volatile
    enforcement_mode: str       # 执行模式：prompt_only/compiler_validated
    conflicts_with: tuple       # 冲突规则
    requires: tuple             # 依赖规则
    supersedes: tuple           # 替代规则
```

### 2.5 PromptAssemblyRequest & PromptAssemblyResult

**PromptAssemblyRequest**（组装请求）：
```python
@dataclass(frozen=True, slots=True)
class PromptAssemblyRequest:
    invocation_kind: str                   # 调用形态
    prompt_pack_refs: tuple               # pack 引用
    prompt_refs: tuple                    # 额外 prompt 引用
    task_prompt_contract: dict            # 任务级契约 section
    graph_node_prompt_contract: dict      # 图节点级契约 section
    skill_prompt_refs: tuple              # skill prompt 引用
    soul_prompt_ref: str                  # soul prompt 引用
    agent_profile_ref: str                # agent profile 引用
    task_environment_ref: str             # 环境引用
```

**PromptAssemblyResult**（组装结果）：
```python
@dataclass(frozen=True, slots=True)
class PromptAssemblyResult:
    assembly_id: str                      # 格式："promptasm:{sha256}"
    invocation_kind: str
    sections: tuple[PromptSection, ...]   # 有序的组装结果
    prompt_pack_refs: tuple
    rejected_refs: tuple                  # 被拒绝的引用列表
    dynamic_projection_refs: tuple
    volatile_state_refs: tuple
    manifest: dict                        # 完整清单
```

**content 属性**：将所有 section 的 content 拼接成一个字符串。

### 2.6 工厂函数

- `prompt_resource_from_dict(payload)`：从字典创建 PromptResource，自动处理 prompt_id/resource_id 默认值
- `prompt_pack_from_dict(payload)`：从字典创建 PromptPack
- `_category_from_resource_type()`/`_subtype_from_resource_type()`/`_owner_layer_from_category()`/`_resource_type_from_category_subtype()`：类型推导函数

---

## 3. Prompt 注册表与持久化（registry.py）

`registry.py`（~15.7 KB，342 行）是 prompt library 的核心存储层。

### 3.1 PromptLibraryRegistry

```python
class PromptLibraryRegistry:
    def __init__(self, base_dir: Path)
```

**存储位置**：`{storage_root}/prompt_library/`
- `prompt_resources.json`：资源存储
- `prompt_packs.json`：pack 存储

### 3.2 资源管理

| 方法 | 功能 |
|------|------|
| `list_resources()` | 合并内置资源 + 持久化资源，返回排序后列表 |
| `list_active_resources(category, subtype)` | 按分类筛选活跃资源 |
| `get_resource(resource_id)` | 按 resource_id 查找 |
| `get_active_resource(prompt_id)` | 按 prompt_id 查找活跃且未废弃的资源 |
| `upsert_resource(resource)` | 新增或更新单条资源 |
| `upsert_resources(resources)` | 批量新增/更新资源 |
| `upsert_task_graph_node_role_prompt(...)` | 为图节点创建 role prompt |

### 3.3 Pack 管理

| 方法 | 功能 |
|------|------|
| `list_packs()` | 合并内置 packs + 持久化 packs |
| `get_pack(pack_id)` | 按 ID 查找 pack |
| `upsert_pack(pack)` | 新增/更新 pack |

### 3.4 规则管理

| 方法 | 功能 |
|------|------|
| `list_prompt_rules()` | 从所有资源的 metadata 中提取 prompt_rule 并排序返回 |

### 3.5 存储架构

**内置资源 vs 持久化资源**的优先级策略：
1. 先从 Python 内置函数加载（list_builtin_*_resources）
2. 再从 JSON 文件加载持久化资源
3. 合并时持久化资源覆盖内置资源（`{**builtin, **stored}`）

**持久化自动规范化（normalize）**：
- `_list_stored_resources(normalize=True)` 读取 JSON 后比对规范化前后是否一致，不一致则重写
- 确保存储格式始终与最新 schema 一致

### 3.6 图节点 prompt 管理

```python
def upsert_task_graph_node_role_prompt(self, *, graph_id, graph_title, domain_id, node, prompt)
```
- 生成 stable resource ID：`prompt.task_graph.{graph_id}.{node_id}.graph_node.role`
- 插入 tags：`(task_graph, domain_id, graph_id)`
- cache_scope 固定为 `"static"`

### 3.7 环境 prompt 注册

- `list_builtin_environment_prompt_resources()`：从 task_system 的默认环境 prompt spec 生成资源
- `list_environment_prompt_resources_from_backend_dir(base_dir)`：扫描项目中的环境定义文件，提取环境级 prompt
- `_environment_prompt_resources_from_definitions(definitions)`：通用的环境定义→资源转换函数

---

## 4. Prompt 组装管线（assembly.py）

`assembly.py`（~22 KB）是整个系统的核心组装逻辑。

### 4.1 PromptAssemblyService

```python
class PromptAssemblyService:
    def __init__(self, base_dir: Path)
    def assemble(self, request: PromptAssemblyRequest) -> PromptAssemblyResult
    def assemble_refs(self, *, invocation_kind, prompt_refs, ...) -> PromptAssemblyResult
```

### 4.2 assemble 流程

```
PromptAssemblyRequest
        │
        ▼
  ① 解析 pack_refs → 按优先级过滤 pack（status=active, invocation_kind 匹配, agent/environment 过滤）
        │
        ▼
  ② 解析 prompt_refs 顺序：pack 内 refs → request.prompt_refs → skill_refs → soul_ref
        │
        ▼
  ③ 按 order 依次解析每个 prompt_ref → 获取 PromptResource → 过滤（active, invocation_kind 匹配）
        │
        ▼
  ④ 生成 PromptSection（section_id = "{category}.{subtype}:{order}"）
        │
        ▼
  ⑤ 如果 invocation_kind == "task_prompt_contract"，插入任务/图节点契约 section
        │
        ▼
  ⑥ enforce_prompt_authority_order()：按 owner_layer 优先级排序
        │
        ▼
  ⑦ 构建 manifest（assembly_request_fingerprint, cache_boundary, layer_summary 等）
        │
        ▼
  ⑧ build_rule_diagnostics()：规则冲突/缺失/作用域检测
        │
        ▼
  ⑨ 返回 PromptAssemblyResult
```

### 4.3 Pack 过滤规则

每个 pack 必须满足以下所有条件：
1. `pack.status == "active"`
2. `pack.invocation_kind == request.invocation_kind`
3. `_pack_rejection_reason(pack)` 返回空（agent_ref 和 environment_ref 匹配）
4. 不满足时加入 `rejected_refs`

### 4.4 资源过滤规则

每个 prompt resource 必须满足：
1. 未标记 `deprecated_for_new_runtime`
2. `status == "active"`
3. `allowed_invocation_kinds` 匹配
4. `allowed_agent_refs` 匹配
5. `allowed_environment_refs` 匹配
6. 不满足时加入 `rejected_refs`

### 4.5 Prompt 权威顺序

```python
_PROMPT_LAYER_PRECEDENCE = {
    "system": 0,
    "override": 5,
    "coordinator": 10,
    "agent": 20,
    "personality": 25,
    "runtime": 30,
    "environment": 40,
    "lifecycle": 45,
    "tool": 50,
    "skill": 60,
    "project": 70,
    "contract": 80,
    "unknown": 100,
}
```

`enforce_prompt_authority_order()` 按 `(layer_precedence, order, original_index)` 三元组排序，确保：
- 系统提示（system）永远在最前
- 契约提示（contract）在最后
- 同层内部按 order 和原始顺序排列

### 4.6 契约 Section 处理

当 `invocation_kind == "task_prompt_contract"` 时：
1. 将 `task_prompt_contract` 转为 section（category="task", source_ref="task_prompt_contract"）
2. 将 `graph_node_prompt_contract` 转为 section（category="graph_node"）
3. 如果不是 task_prompt_contract 调用但有 task/graph contract，触发 rejection

### 4.7 Manifest 结构

组装完成后输出的 manifest 包含：
- `assembly_request_fingerprint`：请求指纹哈希
- `section_fingerprint`：section 内容哈希
- `stable_prompt_refs`：稳定 prompt 引用列表
- `stable_contract_refs`：稳定契约引用列表
- `prompt_pack_refs`：使用的 pack 引用
- `rejected_refs`：被拒绝的引用+原因
- `cache_scope_order`：按 section 顺序的缓存范围
- `cache_boundary`：缓存边界报告
- `layer_summary`：各层的 section 计数
- `prompt_precedence`：提示优先级报告
- `prompt_authority`：提示权威清单
- `prompt_rules`：规则诊断结果

---

## 5. Manifest 与运行时投影（manifest.py）

`manifest.py`（~5.6 KB，121 行）构建运行时可直接消费的轻量清单。

### 5.1 RuntimePromptManifest

```python
@dataclass(frozen=True, slots=True)
class RuntimePromptManifest:
    manifest_id: str                          # "rtprompt:{sha256}"
    invocation_kind: str
    prompt_pack_refs: tuple
    stable_prompt_refs: tuple
    stable_contract_refs: tuple
    rejected_refs: tuple
    dynamic_projection_refs: tuple
    volatile_state_refs: tuple
    cache_boundary: dict                      # 缓存边界信息
    prompt_rules: dict                        # 规则信息
    token_estimate: dict                      # token 估算
    diagnostics: dict                         # 诊断信息
```

### 5.2 build_runtime_prompt_manifest()

```python
def build_runtime_prompt_manifest(
    *,
    invocation_kind: str,
    assembly: PromptAssemblyResult,
    packet_id: str = "",
    dynamic_projection_refs: tuple = (),
    volatile_state_refs: tuple = (),
) -> RuntimePromptManifest:
```

**构造逻辑**：
1. 从 assembly.sections 提取 stable_prompt_refs 和 stable_contract_refs
2. 计算 cache_scope 分布（static/static_environment/session_stable/task_stable 计数）
3. 计算 total_chars（token 估算）
4. 构建 diagnostics（assembly_id, fingerprints, layer_summary, prompt_authority, precedence）

**缓存边界报告**包含：
- `static_section_count`：静态缓存 section 数
- `stable_prompt_section_count`：总 section 数
- `cache_scope_counts`：按 scope 的 section 分布
- `volatile_state_after_stable_sections`：标记 volatile 状态插入

---

## 6. Prompt Pack 体系（packs.py）

`packs.py`（~19 KB）定义内置的 runtime prompt packs。

### 6.1 内置 Pack 列表

| Pack ID | invocation_kind | 包含的 prompt refs |
|---------|----------------|-------------------|
| `runtime.pack.single_agent_turn` | `single_agent_turn` | foundation(7) + single_agent_turn + 9个规则 |
| `runtime.pack.task_execution` | `task_execution` | foundation(7) + task_execution + 9个规则 |
| `runtime.pack.graph_node_execution` | `task_execution` | foundation(7) + graph_node_execution + 3个规则 |
| `runtime.pack.observation_followup` | `tool_observation_followup` | foundation(7) + observation_followup + 7个规则 |
| `runtime.pack.semantic_compaction` | `semantic_compaction` | semantic_compaction（仅 context_compactor_agent 可用） |

### 6.2 运行时提示词

packs.py 中内置了 5 个核心运行时 prompt 文本：

1. **RUNTIME_SINGLE_AGENT_TURN_PROMPT**：单轮 agent turn 的执行协议
   - 语义判断、动作选择、工具调用、输出格式
   - 强调用户可见内容和真实动作一致

2. **RUNTIME_TASK_EXECUTION_PROMPT**：持续任务执行协议
   - 合同推进、材料权重、阶段总结
   - 不允许在持续任务中开启新的处理流程

3. **RUNTIME_GRAPH_NODE_EXECUTION_PROMPT**：图节点执行协议
   - 节点合同驱动、上游边授权、输出合同
   - 输出格式固定为 JSON，包含 authority、action_type、public_progress_note、public_action_state、final_answer

4. **RUNTIME_OBSERVATION_FOLLOWUP_PROMPT**：观察跟进协议
   - 基于观察结果判断下一步
   - active_work_control 语义裁决

5. **RUNTIME_SEMANTIC_COMPACTION_PROMPT**：语义压缩协议
   - 生成 context_recovery_package
   - 专供 context_compactor_agent 使用

### 6.3 内置资源列表

`list_builtin_runtime_prompt_resources()` 返回上述 5 个 runtime prompt 的 PromptResource 对象，每个都标记了 `requires` 规则依赖。

### 6.4 default_pack_ref_for_invocation()

```python
def default_pack_ref_for_invocation(invocation_kind: str) -> str:
    mapping = {
        "single_agent_turn": "runtime.pack.single_agent_turn",
        "task_execution": "runtime.pack.task_execution",
        "tool_observation_followup": "runtime.pack.observation_followup",
        "semantic_compaction": "runtime.pack.semantic_compaction",
    }
```

---

## 7. 结构分层

### 7.1 Prompt 权威层级（按优先级升序）

| 层级 | 优先级 | 说明 |
|------|--------|------|
| system | 0 | 系统基础提示（最高优先级） |
| override | 5 | 覆盖提示 |
| coordinator | 10 | 协调提示 |
| agent | 20 | Agent 工作角色提示 |
| personality | 25 | 人格提示 |
| runtime | 30 | 运行时提示 |
| environment | 40 | 环境提示 |
| lifecycle | 45 | 生命周期提示 |
| tool | 50 | 工具提示 |
| skill | 60 | Skill 提示 |
| project | 70 | 项目提示 |
| contract | 80 | 契约提示（最低优先级） |
| unknown | 100 | 未知（兜底） |

### 7.2 缓存层级体系

| 缓存范围 | 说明 |
|----------|------|
| static | 全局静态，不随环境/会话/任务变化 |
| static_environment | 环境级静态 |
| session_stable | 会话期间稳定 |
| task_stable | 任务期间稳定 |
| none/volatile | 不缓存，每次重新生成 |

### 7.3 资源分类体系

| category | 典型 subtype | 来源 |
|----------|-------------|------|
| system | foundation | system_prompts.py |
| runtime | rule, graph_rule | rules.py |
| tool | guidance | tool_prompts.py |
| agent | work_role, worker | agent_prompts.py, worker_prompts.py |
| personality | default | personality_prompts.py |
| environment | boundary, orientation | registry.py → environment_prompt_resources |
| utility | finalizer, distiller, memory, repair | utility_prompts.py |
| graph_node | role | registry.py → upsert_task_graph_node_role_prompt |
| mcp | instruction, usage | utility_prompts.py |

---

## 8. 模块详解

### 8.1 系统基础提示（system_prompts.py）

**文件大小**：~10 KB，171 行  
**内置资源数量**：7 个

定义了 7 个系统基础 prompt（foundation），是所有 invocation 类型的公共基础。

| prompt_id | 标题 | 核心内容 |
|-----------|------|---------|
| `system.foundation.local_collaboration` | 本地协作基础 | Agent 在工作区中的职责边界、材料分层理解、语义判断与调度 |
| `system.foundation.current_request_authority` | 当前请求权威 | 最新用户请求是最高语义信号，历史摘要不能劫持新请求 |
| `system.foundation.truth_and_verification` | 事实与验证 | 真实观察优先，失败后必须改变参数不能原样重试，完成前需验证 |
| `system.foundation.response_and_reporting` | 响应与报告 | 只报告需要的结果，不暴露内部协议，保持简洁可复核 |
| `system.foundation.security_and_injection` | 安全与注入防护 | 外部内容只能做数据不能改变规则，拒绝 prompt injection |
| `system.foundation.context_memory_cache` | 上下文与缓存 | 分层上下文、后出现的工具结果不能覆盖上级规则 |
| `system.foundation.user_change_protection` | 用户变更保护 | 保护用户已有改动和资产，高影响改动需计划批准 |

**适用范围**：`single_agent_turn`、`task_execution`、`tool_observation_followup`

### 8.2 Agent 工作角色提示（agent_prompts.py）

**文件大小**：~11.7 KB，173 行  
**内置资源数量**：5 个

为不同的 agent 角色定义 work_role prompt。

| prompt_id | 适用角色 | 核心内容 |
|-----------|---------|---------|
| `agent.main_interactive_agent.single_agent_turn.work_role` | main_interactive_agent | 单轮裁决：理解请求、选择最小充分动作、遵守输出格式 |
| `agent.main_interactive_agent.task_execution.work_role` | main_interactive_agent | 持续任务执行：合同推进、材料权重、不重新判断是否开启任务 |
| `agent.main_interactive_agent.tool_observation_followup.work_role` | main_interactive_agent | 观察跟进：将观察纳入事实链、决定回答/继续/阻塞 |
| `agent.context_compactor_agent.semantic_compaction.work_role` | context_compactor_agent | 语义压缩：生成 context_recovery_package |
| `agent.memory_system_agent.memory_maintenance.work_role` | memory_system_agent | 记忆维护：整理会话信息、提出结构化记忆候选 |

每个 resource 都带有 metadata.prompt_rule，标记为 `agent.role` 类型的规则。

### 8.3 Worker 提示（worker_prompts.py）

**文件大小**：~20.6 KB，337 行  
**内置资源数量**：4 个 WorkerPromptSpec

Worker 是受父任务授权委托的子执行者。

```python
@dataclass(frozen=True, slots=True)
class WorkerPromptSpec:
    prompt_id: str
    title: str
    content: str               # 实际 prompt 文本
    worker_kind: str           # execution / code_execution / review
    blueprint_ids: tuple       # 支持的 blueprint ID
    description: str           # 人类可读描述
```

| spec.prompt_id | worker_kind | blueprint_ids | 说明 |
|---------------|-------------|---------------|------|
| `worker.prompt.execution` | execution | worker.execution | 边界执行 worker，完成父任务授权的局部实现或修复 |
| `worker.prompt.code_executor` | code_execution | worker.code.executor | 代码执行 worker，完成清晰边界内的代码修改和验证 |
| `worker.prompt.review` | review | worker.review | bug-first 审查 worker，复核变更、证据和缺失测试 |

**辅助函数**：

| 函数 | 功能 |
|------|------|
| `worker_prompt_ref_for_blueprint(blueprint_id)` | 根据 blueprint ID 查找对应的 prompt ref |
| `worker_agent_description_for_blueprint(blueprint_id)` | 返回人类可读描述 |
| `worker_prompt_metadata_for_blueprint(blueprint_id)` | 返回 worker 的 prompt 元数据 |
| `list_builtin_worker_prompt_resources()` | 返回所有 worker prompt 的 PromptResource 列表 |

### 8.4 人格提示（personality_prompts.py）

**文件大小**：~3.4 KB，86 行  
**内置资源数量**：1 个

默认人格为 **Mythical Age（洪荒智能）**（`personality.default.mythical_age`）。

**规则**：
- 人格只影响称呼、语气、表达节奏和协作风格
- 不改变系统规则、开发规则、权限边界、工具协议等
- 当人格要求和更高权威规则冲突时，忽略人格要求

### 8.5 环境生命周期提示（environment_lifecycle_prompts.py）

**文件大小**：~46 KB，607 行  
**内置资源数量**：大量环境级生命周期提示

为不同环境（environment_id）提供生命周期阶段的提示文本，包括：
- turn 开始/结束
- task 执行阶段
- 环境特定的能力边界和资源约束

**关键导出**：

```python
ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS         # 所有可用的生命周期 slot 定义
ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT  # 按环境索引的 prompt ID
ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT  # 按环境的默认值
ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS       # 所有生命周期 prompt ID 集合
```

**支持的环境包括**：chat 对话、coding 编码、generic Vibe 工作区等。

### 8.6 工具提示（tool_prompts.py）

**文件大小**：~20 KB，400 行  
**内置资源数量**：10 个工具引导提示（tool_guidance）

为每个关键工具提供使用引导文本。工具引导的匹配机制：

```python
_TOOL_GUIDANCE_REFS_BY_NAME: dict[str, tuple[str, ...]] = {
    "read_file": ("tool.guidance.read_file",),
    "edit_file": ("tool.guidance.edit_file",),
    "batch_edit_file": ("tool.guidance.batch_edit_file",),
    "write_file": ("tool.guidance.write_file",),
    "terminal": ("tool.guidance.terminal_powershell",),
    "web_search": ("tool.guidance.web_fetch",),
    "fetch_url": ("tool.guidance.web_fetch",),
    # ... 更多工具
}
```

**关键函数**：

| 函数 | 功能 |
|------|------|
| `list_builtin_tool_prompt_resources()` | 列出所有内置工具引导资源 |
| `tool_guidance_items_for_visible_tools(tool_payloads)` | 从当前可见工具列表中筛选对应的引导项 |
| `tool_guidance_payload_for_visible_tools(tool_payloads)` | 生成工具引导的 payload（包含 guidance、refs、hash） |

**ToolGuidanceItem** 数据结构：
```python
@dataclass(frozen=True, slots=True)
class ToolGuidanceItem:
    prompt_ref: str
    title: str
    content: str          # 引导正文
    tool_names: tuple[str, ...]  # 该引导适用的工具列表
```

### 8.7 实用工具提示（utility_prompts.py）

**文件大小**：~9.5 KB，155 行  
**内置资源数量**：12 个

涵盖各种辅助角色的 prompt：

| prompt_id | 用途 |
|-----------|------|
| `utility.finalizer.rag_answer` | RAG 回答最终整理 |
| `utility.distiller.search_evidence` | 搜索证据提炼 |
| `utility.memory.durable_recall_selector` | 长期记忆召回选择 |
| `utility.title_generation.session` | 会话标题生成 |
| `utility.summarize_history.context_recovery` | 历史上下文恢复摘要 |
| `utility.planner.readonly_task_plan` | 只读任务计划 |
| `utility.verifier.readonly_delivery` | 只读交付验证 |
| `utility.repair.single_agent_admission` | 准入修复 |
| `utility.repair.single_agent_protocol` | 协议修复 |
| `utility.repair.task_action_json` | 任务动作 JSON 修复 |
| `mcp.prompt.server_instructions` | MCP 服务器指令 |
| `mcp.prompt.capability_usage` | MCP 能力使用说明 |

### 8.8 IO 能力提示（io_capability_prompts.py）

**文件大小**：~5.9 KB，55 行  
**内置资源数量**：5 个工具引导文本

提供核心 IO 工具的详细使用指引：
- `TOOL_READ_FILE_GUIDANCE`：读取文件引导
- `TOOL_EDIT_FILE_GUIDANCE`：编辑文件引导
- `TOOL_BATCH_EDIT_FILE_GUIDANCE`：批量编辑引导
- `TOOL_WRITE_FILE_GUIDANCE`：写入文件引导
- `TOOL_TERMINAL_POWERSHELL_GUIDANCE`：PowerShell 终端引导

---

## 9. 规则系统（rules.py）

`rules.py`（~58 KB，1054 行）是整个 prompt library 中最大的文件，定义了规则声明、内置规则列表、编译器、诊断和校验逻辑。

### 9.1 内置规则资源

定义了 24+ 个内置规则资源（通过 `_rule_resource()` 工厂函数创建），按 rule_kind 分类：

**system.foundation 类型**（不可冲突、不可自行构建）：
- `system.foundation.local_collaboration`
- `system.foundation.current_request_authority`
- `system.foundation.truth_and_verification`
- `system.foundation.response_and_reporting`
- `system.foundation.security_and_injection`
- `system.foundation.context_memory_cache`
- `system.foundation.user_change_protection`

**runtime.protocol 类型**（每个 invocation 只能有一个）：
- `runtime.rule.system_call_protocol`：系统调用协议
- `runtime.rule.turn_decision_alignment`：决策对齐
- `runtime.rule.tool_use`：工具使用
- `runtime.rule.output_boundary`：输出边界
- `runtime.rule.error_recovery`：错误恢复
- `runtime.rule.context_memory`：上下文记忆
- `runtime.rule.lifecycle_control`：生命周期控制
- `runtime.rule.permission_denial`：权限拒绝
- `runtime.rule.subagent_delegation`：子 agent 委派
- `runtime.rule.subagent_invocation_protocol`：子 agent 调用协议
- `runtime.rule.multi_tool_scheduling`：多工具调度
- `runtime.rule.plan_mode_boundary`：计划模式边界

**runtime.instruction 类型**：
- `runtime.rule.file_management.generic`：文件管理

**environment.orientation 类型**：
- `environment.rule.chat_workspace`
- `environment.rule.coding_workspace`

**coding.rule 类型**：
- `coding.rule.core_work_protocol`
- `coding.rule.codebase_inspection`
- `coding.rule.large_scope_exploration`
- `coding.rule.editing`
- `coding.rule.verification`
- `coding.rule.debug_discipline`
- `coding.rule.git_safety`
- `coding.rule.windows_shell`
- `coding.rule.task_progress`

**graph.contract 类型**：
- `graph.rule.node_boundary`：图节点边界
- `graph.rule.node_output_contract`：图节点输出契约

### 9.2 PromptRuleCompiler

```python
class PromptRuleCompiler:
    def compile(self, sections, *, invocation_kind, fail_on_rejected=True)
```

**编译流程**：
1. 从每个 section 的 metadata 中提取 prompt_rule
2. 调用 `build_rule_diagnostics()` 进行诊断
3. 如果 `fail_on_rejected=True` 且存在被拒绝的规则，抛出 ValueError
4. 返回 `PromptRuleAssemblyResult`

### 9.3 规则诊断（build_rule_diagnostics）

```python
def build_rule_diagnostics(sections, *, invocation_kind) -> dict
```

**诊断检查项**：

1. **依赖检查**：rule.requires 中的依赖必须在规则集合中
2. **冲突检查**：rule.conflicts_with 中的冲突规则不能同时存在
3. **作用域检查**（`_rule_scope_rejection_reason`）：
   - invocation_kind 匹配
   - owner_layer 匹配
   - category 匹配（environment/agent/personality/graph_node 等）
4. **缓存边界检查**（`_cache_boundary_rejection_reason`）：
   - section 的 cache_scope 与 rule 的 cache_tier 兼容
   - static_environment 只适用于 environment 分类
   - session_stable 适用于 agent/personality/skill
   - task_stable 适用于 task/graph_node
   - global_static 不适用于 task/graph_node
5. **多协议检测**：runtime.protocol 类型规则数量不能 > 1
6. **开发者风格检测**：检测 prompt 正文是否包含"这是 runtime 节点"等开发者风格文本

**输出结构**：
```python
{
    "invocation_kind": str,
    "rule_refs": list[str],
    "rule_kinds": list[str],
    "rule_owner_layers": list[str],
    "rule_cache_tiers": list[str],
    "rule_enforcement_modes": list[str],
    "rule_kind_counts": dict[str, int],
    "rejected_rules": list[dict],
    "coverage": {
        "rule_count": int,
        "has_system_foundation": bool,
        "has_runtime_protocol": bool,
        "has_system_call_protocol": bool,
        "has_turn_decision_alignment": bool,
        "has_output_boundary": bool,
        "has_error_recovery": bool,
    },
}
```

### 9.4 辅助函数

| 函数 | 功能 |
|------|------|
| `prompt_rule_from_resource(resource)` | 从 PromptResource.metadata 提取 PromptRule |
| `prompt_rule_from_section(section)` | 从 PromptSection.metadata 提取 PromptRule |
| `rule_metadata(...)` | 构建规则元数据字典（用于嵌入 resource.metadata） |
| `_rule_resource(...)` | 创建内置规则 PromptResource |
| `_prompt_rule_from_payload(...)` | 从字典解析 PromptRule |
| `_cache_tier_from_scope(scope)` | 缓存范围→缓存层级映射 |
| `_cache_boundary_rejection_reason(rule, section)` | 缓存边界冲突检测 |
| `_rule_scope_rejection_reason(rule, section, invocation_kind)` | 规则作用域冲突检测 |
| `_effective_invocation_kind_for_section(section, packet_invocation_kind)` | 推导 section 的有效 invocation_kind |
| `_rule_owner_matches_section(rule_owner, section_owner)` | 检查 owner 层级匹配 |
| `_developer_style_prompt_text_reason(content)` | 检测开发者风格文本 |
| `_allowed_section_tiers_for_rule_cache_tier(cache_tier)` | 获取缓存层级允许的 section 层级集合 |

---

## 10. 关键数据流

### 10.1 Prompt 组装主流程

```
运行时发起组装请求
        │
        ▼
PromptAssemblyService.assemble(request)
        │
        ├── PromptLibraryRegistry 加载：内置资源 + JSON 持久化资源
        │
        ├── Pack 解析：过滤 active + invocation_kind 匹配的 pack
        │
        ├── Prompt Ref 解析：pack 内 refs → 额外 refs → skill refs → soul ref
        │
        ├── 去重：seen set 防止重复
        │
        ├── Section 构建：为每个 prompt_ref 生成 PromptSection
        │
        ├── 契约 Section：task_prompt_contract / graph_node_prompt_contract
        │
        ├── 权威排序：enforce_prompt_authority_order()
        │
        ├── Manifest 构建：fingerprint、cache_boundary、layer_summary
        │
        ├── 规则诊断：build_rule_diagnostics()
        │
        └── 返回 PromptAssemblyResult
```

### 10.2 规则编译流程

```
PromptAssemblyResult.sections
        │
        ▼
PromptRuleCompiler.compile(sections)
        │
        ├── 从每个 section.metadata 提取 prompt_rule
        ├── build_rule_diagnostics() → 依赖/冲突/作用域/缓存/多协议检查
        ├── fail_on_rejected? 抛出 ValueError
        └── 返回 PromptRuleAssemblyResult
```

### 10.3 Manifest 构建流程

```
PromptAssemblyResult
        │
        ▼
build_runtime_prompt_manifest(assembly)
        │
        ├── 提取 stable_prompt_refs / stable_contract_refs
        ├── 计算 cache_scope_counts
        ├── 计算 token_estimate (total_chars)
        └── 构建 diagnostics（fingerprint、layer_summary、priority、authority）
```

---

## 11. 文件索引

| 文件名 | 大小 | 行数 | 核心类/函数 |
|--------|------|------|-----------|
| `__init__.py` | 3.7 KB | 98 | 公共 API 导出 |
| `agent_prompts.py` | 11.7 KB | 173 | MAIN_INTERACTIVE_*_PROMPT, list_builtin_agent_prompt_resources |
| `assembly.py` | 22.0 KB | 完整 | PromptAssemblyService, enforce_prompt_authority_order |
| `environment_lifecycle_prompts.py` | 46.1 KB | 607 | 环境生命周期 slot 定义、按环境的 prompt 映射 |
| `io_capability_prompts.py` | 5.9 KB | 55 | TOOL_*_GUIDANCE 引导文本 |
| `manifest.py` | 5.6 KB | 121 | RuntimePromptManifest, build_runtime_prompt_manifest |
| `models.py` | 16.0 KB | 408 | PromptResource, PromptPack, PromptSection, PromptRule, PromptAssemblyRequest/Result |
| `packs.py` | 19.0 KB | 完整 | 内置 pack 定义、运行时 prompt 文本、default_pack_ref_for_invocation |
| `personality_prompts.py` | 3.4 KB | 86 | Mythical Age 人格提示 |
| `registry.py` | 15.7 KB | 342 | PromptLibraryRegistry, 持久化 CRUD, 环境 prompt 注册 |
| `rules.py` | 58.2 KB | 1054 | 24+ 内置规则, PromptRuleCompiler, build_rule_diagnostics |
| `system_prompts.py` | 10.0 KB | 171 | 7 个系统基础 foundation prompt |
| `tool_prompts.py` | 20.0 KB | 400 | ToolGuidanceItem, _TOOL_GUIDANCE_REFS_BY_NAME, tool_guidance_payload_for_visible_tools |
| `utility_prompts.py` | 9.5 KB | 155 | RAG/蒸馏/记忆/修复/规划/MCP 等 12 个实用 prompt |
| `worker_prompts.py` | 20.6 KB | 337 | WorkerPromptSpec, 4 个 worker prompt, 蓝图查询函数 |

---

## 12. 技术细节汇总

### 12.1 代码规模

| 指标 | 数值 |
|------|------|
| 源文件数 | 15 个 |
| 总代码量 | ~213 KB |
| 最大文件 | rules.py（58.2 KB / 1054 行） |
| 最小文件 | personality_prompts.py（3.4 KB / 86 行） |

### 12.2 资源统计

| 资源类型 | 数量 |
|---------|------|
| 系统基础 foundation | 7 |
| 运行时规则（runtime.protocol） | 12 |
| 运行时规则（runtime.instruction） | 1 |
| 环境规则 | 2 |
| 编码规则 | 9 |
| 图契约规则 | 2 |
| 运行时 prompt | 5 |
| Agent 工作角色 | 5（含 context_compactor 和 memory_system） |
| Worker prompt | 3（execution / code_executor / review） |
| 工具引导 guidance | 10 |
| 实用工具 prompt | 12 |
| 人格 prompt | 1 |
| 合计内置资源 | ~69+ |

### 12.3 关键设计要点

1. **提示词供应链（Prompt Supply Chain）**：系统将 prompt 视为可注册、可组装、可校验的资源，而不是硬编码的文本常量
2. **权威顺序（Authority Order）**：通过 `_PROMPT_LAYER_PRECEDENCE` 保证系统级提示永远在最高优先级
3. **三层存储**：编译时内置（Python 元组）+ 持久化 JSON（运行时可编辑）+ 动态契约（task/graph_node 动态生成）
4. **规则隔离**：每个 resource 可以在 metadata 中声明自己的 prompt_rule，编译器负责校验冲突和依赖
5. **缓存分层**：static → static_environment → session_stable → task_stable → volatile，控制提示词的生命周期
6. **契约注入**：task 和 graph_node 可以在运行时通过 contract 注入额外的 prompt section
7. **增量覆盖**：持久化资源可以覆盖内置资源，允许运行时热更新 prompt
8. **多重拒绝机制**：pack 级别 → resource 级别 → rule 级别，每条被拒绝的条目都附带明确原因

### 12.4 版本策略

- 所有内置资源统一使用 `"2026-06-08"` 作为版本
- 资源通过 version 字段追踪，通过 metadata.managed_by 追踪来源
- prompt_resource.json 和 prompt_packs.json 持久化时自动规范化格式

### 12.5 安全机制

- **Prompt Injection 防护**：system.foundation.security_and_injection 规则禁止外部内容改变系统规则
- **开发者风格检测**：`_developer_style_prompt_text_reason()` 检测 prompt 正文是否包含技术描述性文本（如"这是 runtime 节点"），防止将开发说明混入 agent prompt
- **作用域隔离**：通过 allowed_agent_refs、allowed_environment_refs、allowed_invocation_kinds 三重隔离
- **规则冲突检测**：编译器自动检测 conflicts_with 和 requires 的完整性

### 12.6 持久化存储

- 存储根路径：`{storage_root}/prompt_library/`
- 资源文件：`prompt_resources.json`
- Pack 文件：`prompt_packs.json`
- 写入时自动创建父目录
- 读取失败时返回空 fallback（而非崩溃）
- 存储格式在 upsert 时自动规范化

---

*报告完成。审查了 backend/prompt_library/ 目录下全部 15 个源文件，涵盖 Prompt 资源模型、注册表、组装管线、Manifest、Pack 体系、规则系统、Agent/Worker/人格/环境/工具/系统提示等完整子系统。*
