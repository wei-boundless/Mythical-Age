# 第 7 篇：Prompt Cache 原则书

Prompt Cache 不是一个“把提示词写短一点”的优化项，而是 agent 运行架构的稳定性结果。

一个成熟 agent 的缓存命中率，来自稳定的上下文分层、单调追加的事件历史、明确的压缩替换点，以及不会随请求抖动的 provider 参数。任何为了提升命中率而削弱语义控制、删除必要证据、降低 agent 判断质量的做法，都是错误方向。

本原则书用于约束本项目后续所有 prompt cache、上下文装配、运行轨迹 replay、prompt 预算与 provider payload 的调整。

---

## 一、最高原则

### 1. 语义控制优先于缓存命中

缓存命中是成本和延迟优化，不是 agent 正确性的上级目标。

不允许为了缓存命中：

- 删除 agent 必须知道的任务目标、边界、证据、工具结果或失败路径。
- 把明确角色、契约、裁决标准改成含糊短句。
- 把需要模型判断的信息移到不可见位置。
- 用统计好看替代真实 provider 命中。
- 通过降低测试断言、跳过失败用例、mock 核心逻辑制造通过。

允许做的是：

- 把只需说一次的规则放入稳定层。
- 把重复动态信息改为引用、索引、摘要或恢复入口。
- 把历史轨迹改为 append-only。
- 把压缩做成明确替换事件，而不是偷偷改写旧历史。

### 2. 缓存由稳定前缀产生，不由局部补丁产生

Prompt Cache 的核心不是“某个函数里算一个 hash”，而是整条请求前缀在多轮调用中保持字节稳定。

稳定前缀必须满足：

- 内容层级固定。
- 字段顺序固定。
- 参数集合固定。
- 历史顺序单调追加。
- 压缩替换有明确边界。
- 动态内容只能出现在动态层，不能污染静态层。

如果一个模块每轮重新扫描、重新排序、重新推断上下文，那么它天然不适合作为缓存前缀权威。

### 3. 事件日志拥有历史顺序权

工具结果、失败、模型回复、用户补充、恢复动作都属于运行历史。运行历史的顺序只能由不可变事件源决定。

本项目的顺序权应归属于 runtime event log 或同等不可变 ledger：

```text
RuntimeEventLog.offset
-> RuntimeObservation / RuntimeEvent refs
-> replay entry sequence
-> prompt replay prefix
```

不允许由以下派生状态决定 replay 顺序：

- `latest_tool_results`
- `active_failures`
- `historical_failures`
- 当前 UI 投影列表
- 当前 monitor 状态
- 当前 task_state 字段遍历顺序

这些派生状态可以补充同一个 replay entry 的信息，但不能决定旧 entry 在 prompt 中的位置。

---

## 二、成熟 agent 的共同做法

### 1. Claude Code 的启发

Claude Code 的缓存设计重点不是“少发内容”，而是“让该稳定的内容保持稳定”。

可迁移原则：

- `CLAUDE.md` 一类长期规则属于稳定 memory，不应每轮作为动态状态重排。
- transcript 是可持久化历史，不是每轮临时拼出来的随机列表。
- compaction 是明确事件，不能偷偷改旧消息内容。
- provider usage 中的 cache read / cache creation 是真实反馈，统计层必须贴近 provider 事实。
- `cache_control` 一类缓存标记属于请求协议层，不能散落在业务 prompt 模板里。

### 2. Codex 的启发

Codex 的关键思想是 thread/turn 模型：

```text
thread identity
-> stable instructions
-> append-only turn history
-> explicit compacted history replacement
-> next turn
```

可迁移原则：

- cache key 应绑定稳定会话或线程身份，不能混入 request id、segment id 这类单次请求字段。
- base instructions 和动态 input 应分层，不要混成一个每轮重算的大字符串。
- turn history 应追加，不应由当前状态投影反复重排。
- compact 后应产生新的历史基线，而不是让旧历史和新摘要同时争夺权威。

---

## 三、本项目的目标分层

Prompt payload 必须按语义和稳定性分层，而不是简单分成“静态”和“动态”。

### 1. 固定协议层

内容：

- provider 协议要求。
- action JSON 格式。
- 工具调用边界。
- 安全与权限底线。
- 输出通道约束。

原则：

- 每个环境可以有自己的完整协议层。
- 不靠大量运行时条件复用造成抖动。
- 只有协议版本变化才允许变化。

### 2. 环境语义层

内容：

- coding、office、writing、graph task 等环境的完整角色和工作规则。
- 当前环境的工具边界、审查标准、失败处理。

原则：

- 环境之间可以重复必要规则，以换取清晰和稳定。
- 不把开发说明当成 agent prompt。
- 不把只适用于某个环境的规则放进全局层。

### 3. 任务契约层

内容：

- 本次用户目标。
- 任务模式。
- 交付标准。
- 用户明确约束。

原则：

- 每个任务开始时确定。
- 任务期间尽量稳定。
- 用户新指令改变任务时，形成明确更新，而不是偷偷覆盖旧状态。

### 4. 运行历史层

内容：

- 已发生的工具调用。
- 工具结果。
- 失败和恢复。
- 模型已经作出的承诺。

原则：

- 严格 append-only。
- 顺序来自 event offset。
- replay prefix 中已有 entry 不允许被重排。
- 历史太大时用 compact event 替换，不在原地改写。

### 5. 当前游标层

内容：

- 当前进度。
- 当前待决问题。
- 最近需要恢复的引用。
- 指向完整证据的 ref。

原则：

- 可以动态变化。
- 应轻量。
- 不承担历史权威。
- 不重复 replay prefix 中已有的大段证据。

### 6. 诊断统计层

内容：

- provider usage。
- cached tokens。
- cache creation tokens。
- 本地 payload prefix hash。
- cache-sensitive params hash。

原则：

- 统计层只解释事实，不制造事实。
- key 不得混入 request-specific 字段。
- 统计口径必须能反查到 provider 调用记录。

---

## 四、Replay Prefix 原则

Replay prefix 是 prompt cache 的核心风险点。

它必须像成熟 agent 的 thread history 一样工作：旧内容稳定，新内容追加，压缩有事件。

### 1. Replay entry 的权威字段

每个 replay entry 至少应具备：

```text
entry_id
observation_ref
event_offset
entry_kind
tool_name / failure_type
evidence_refs
rehydration_plan
summary
```

其中 `event_offset` 或同等单调 sequence 是排序权威。

### 2. Replay entry 的禁止事项

禁止：

- 以当前列表遍历顺序作为历史顺序。
- 因为 active/historical 状态变化而移动旧 entry。
- 每轮重新生成不稳定 preview 进入缓存前缀。
- 把同一个 observation 以不同 key 反复插入。
- 让失败投影和工具结果投影各自生成独立历史。

### 3. Replay merge 的正确方式

同一 observation 的多个投影只能合并：

```text
tool_result entry
+ active_failure fields
+ historical_failure fields
-> same replay entry
```

合并只能增加字段或补充状态，不能改变 entry 的历史位置。

### 4. 缺少权威顺序时的处理

如果一个记录没有 event offset、observation ref 或持久 sequence：

- 不得插入已缓存 replay prefix 中间。
- 可以放入 current cursor。
- 可以作为尾部动态补充。
- 必须记录诊断，推动上游补齐顺序来源。

---

## 五、Compaction 原则

Compaction 不是删除历史，而是创建新的历史基线。

正确模型：

```text
old append-only history
-> compact decision
-> compact summary / replacement history
-> new baseline
-> append new events
```

错误模型：

```text
old history
-> projector 随机截断/改写/重排
-> 假装还是同一个 prefix
```

Compaction 必须满足：

- 有明确触发条件。
- 有明确覆盖范围。
- 有可追踪 compact event。
- 有恢复入口。
- compact 后旧历史不再和新摘要同时争夺 prompt 权威。

---

## 六、Provider Payload 原则

Provider payload 是最终真实发送给模型的东西。缓存优化必须以 provider payload 为准。

### 1. Cache key 原则

cache key 可以包含：

- provider。
- model。
- thread / task run 稳定身份。
- cache-sensitive 参数 hash。
- stable prefix hash。

cache key 不应包含：

- request id。
- segment id。
- boundary segment id。
- 当前时间。
- 随机 uuid。
- 单次 invocation id。

这些字段可以用于诊断 trace，不能用于稳定缓存分组。

### 2. 参数稳定原则

以下参数变化会破坏缓存前缀或 provider 复用，应在任务期间保持稳定：

- model。
- reasoning / thinking 配置。
- tool schema。
- response format。
- provider beta / extra body。
- system / developer instructions。
- tool calling 协议。

如果必须变化，应形成新的缓存世代，而不是和旧世代混算命中率。

---

## 七、测试与实测原则

### 1. 只写结构测试，不写旧语义测试

Prompt cache 相关测试应验证结构性质：

- 同一批 observation 无论来自哪个派生列表，replay 顺序一致。
- 新 observation 只追加，不重排旧 prefix。
- request id / segment id 改变不会改变 stable cache key。
- current cursor 不重复 replay prefix 的大段内容。
- compact 后生成新的明确 baseline。

不应测试旧 prompt 文案的具体语义句子。

### 2. 必须做真实 provider 实测

静态测试只能证明结构不抖，不能证明 provider 命中。

实测至少应包含：

- 冷启动首轮。
- warm 后多轮。
- 工具结果追加。
- 失败恢复。
- 大文件/大量输出。
- compact 或接近 compact 的长任务。

必须记录：

- per-call cached tokens。
- per-call input tokens。
- stable prefix hash。
- provider payload prefix hash。
- cache-sensitive params hash。
- replay entry refs。
- 公共前缀断点。

---

## 八、红线清单

后续任何 prompt cache 调整，遇到以下做法应立即停止：

- 为了命中率删除必要语义控制。
- 用短 prompt 替代清晰 prompt。
- 把开发说明当 agent prompt。
- 让动态状态进入静态层。
- 让派生投影决定历史顺序。
- 让 request-specific 字段进入 cache key。
- 靠清理测试让数字变好。
- 用本地统计数字替代 provider usage。
- 没跑真实长任务就宣称修复。
- 发现同类问题反复出现仍继续补丁式修改。

---

## 九、审查口诀

每次调整 prompt cache 前，先问九个问题：

1. 这段内容是协议、环境、任务、历史、游标，还是诊断？
2. 它是否必须每轮都出现？
3. 它是否必须每轮都完整出现？
4. 它的顺序权来自哪里？
5. 它是否会随 request id、时间、随机值变化？
6. 它进入 stable prefix 后，下一轮是否还能字节一致？
7. 如果它太大，是应该引用、摘要，还是 compact？
8. 如果它变化，是新事件追加，还是旧事件被改写？
9. 这个改动是否降低了 agent 的真实判断能力？

答不清楚时，不要改 cache。先改结构。

---

## 十、本项目当前修复方向

当前最优先的问题不是继续缩短 prompt，而是修正 replay prefix 的顺序权。

目标链路：

```text
RuntimeEventLog.offset
-> RuntimeObservation.event_offset / replay_sequence
-> task_state_replay_entry
-> append-only replay prefix
-> provider payload stable prefix
-> provider prompt cache hit
```

具体原则：

- `task_state_projector` 不再拥有 replay 排序权。
- `latest_tool_results`、`active_failures`、`historical_failures` 只提供字段补充。
- 已进入 replay prefix 的 entry 位置不可改变。
- 没有权威顺序的记录不能污染 stable prefix。
- 修复后用长任务实测确认分布，而不是只看总命中率。

这就是后续 prompt cache 治理的底线。
