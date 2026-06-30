# Semantic Space Archive

本目录保留早期 agent 语义空间、语义时间、控制域和 prompt 结构研究文档。

这些文档是历史证据和参考材料，不是当前 runtime/context 执行权威。当前实现口径以以下链路为准：

```text
SystemAssetLine
-> ContextLineState
-> ContextCandidateGateway
-> ContextInputEnvelope
-> PhysicalContextInputs
-> PhysicalContextAssembler
```

术语收束规则：

```text
session memory / working memory = 摘要源或事实源
runtime_memory_context = current append hint
confirmed old context = provider success 后的 PhysicalPrefixFrame replay
frontend projection = public projection，不进入 provider/model context
runtime_control_signal_tail = 当前 turn 的控制/修复反馈动态尾
```

不要用本目录旧文档中的 `session memory`、`memory prefix`、`provider old context` 直接解释当前四段物理拼接。
