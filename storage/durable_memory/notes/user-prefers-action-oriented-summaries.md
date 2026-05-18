---
schema_version: durable-memory.v3
title: 用户偏好行动导向的总结输出
summary: 用户要求报告结论以行动建议形式输出，每条带行动动词，面向业务负责人汇报场景。复杂问题结论前置，再补依据。
canonical_statement: 用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置，再补依据。
type: user
memory_class: preference
tags: [user, preference, 用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置，再补依据。, 用户偏好行动导向的总结输出, 用户要求报告结论以行动建议形式输出，每条带行动动词，面向业务负责人汇报场景。复杂问题结论前置，再补依据。, 用户输出偏好]
retrieval_hints: [用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置，再补依据。, 用户偏好行动导向的总结输出, 用户要求报告结论以行动建议形式输出，每条带行动动词，面向业务负责人汇报场景。复杂问题结论前置，再补依据。, 用户输出偏好, 行动建议格式, 结论前置, 业务汇报风格]
created_at: 2026-05-18T14:33:48+00:00
updated_at: 2026-05-18T17:16:41+00:00
created_by: agent:1
source_session_id: 177078addbbd4dc8986bcc411ba934b6
source_role: conversation
source_message_excerpt: message:32 用户：'记住：以后复杂问题先给结论。' message:33 助手确认：'记住了。以后复杂问题先给结论，再补依据和细节。'
confidence: high
status: active
last_confirmed_at: 2026-05-18T17:16:41+00:00
scope: project
stability: stable
source_kind: memory_maintenance_agent
eligible_for_injection: true
review_after: 
supersedes: user-prefers-action-oriented-summaries
invalidation_reason: 
---

## Canonical Memory
用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置，再补依据。

## Why Stored
用户明确要求'以后复杂问题先给结论'，这是跨会话稳定的输出格式偏好，与已有的行动导向偏好互补，合并保存可统一指导后续所有复杂问题的回答结构。

## How To Apply
在回答任何复杂问题时，先给出简洁结论，再补充依据和细节。报告类任务继续使用行动动词驱动的行动建议格式。

## Source Evidence
message:32 用户：'记住：以后复杂问题先给结论。' message:33 助手确认：'记住了。以后复杂问题先给结论，再补依据和细节。'

## Maintenance Receipt
- run_id: memory-maintenance:6b4cfe84bb4e404aa286233632a42f49:34
- source_message_refs: message:32, message:33
