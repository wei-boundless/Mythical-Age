---
schema_version: durable-memory.v3
title: 用户要求明确进度反馈
summary: 用户反复询问修复进度，对‘等待继续执行’等笼统回答表达不满，希望助手给出明确诊断或进度状态。
canonical_statement: 当用户询问任务进度时，必须提供具体的已完成或待完成事项，不能使用‘等待指示’等模糊表述。
type: user
memory_class: preference
tags: [user, preference, 当用户询问任务进度时，必须提供具体的已完成或待完成事项，不能使用‘等待指示’等模糊表述。, 用户要求明确进度反馈, 用户反复询问修复进度，对‘等待继续执行’等笼统回答表达不满，希望助手给出明确诊断或进度状态。, 用户询问进度]
retrieval_hints: [当用户询问任务进度时，必须提供具体的已完成或待完成事项，不能使用‘等待指示’等模糊表述。, 用户要求明确进度反馈, 用户反复询问修复进度，对‘等待继续执行’等笼统回答表达不满，希望助手给出明确诊断或进度状态。, 用户询问进度, 进度反馈, 明确回答, 不要模糊]
created_at: 2026-05-29T22:43:48+00:00
updated_at: 2026-05-29T22:43:48+00:00
created_by: agent:1
source_session_id: session-fd1753a572db47ca
source_role: conversation
source_message_excerpt: message:25: '修复到哪了'；message:27: '我问 你  你修复到哪了'；message:26和28助手回复‘等待继续执行’等。
confidence: high
status: active
last_confirmed_at: 
scope: project
stability: stable
source_kind: memory_maintenance_agent
eligible_for_injection: true
review_after: 
supersedes: 
invalidation_reason: 
---

## Canonical Memory
当用户询问任务进度时，必须提供具体的已完成或待完成事项，不能使用‘等待指示’等模糊表述。

## Why Stored
用户对助手模糊回复表达强烈不满，该偏好影响所有进度查询场景，需长期遵从以避免信任流失。

## How To Apply
当被问及任务进度时，直接告知已完成的步骤、当前正在尝试的方案或待解决的障碍，避免说‘等待继续执行’等无实质内容。

## Source Evidence
message:25: '修复到哪了'；message:27: '我问 你  你修复到哪了'；message:26和28助手回复‘等待继续执行’等。

## Maintenance Receipt
- run_id: memory-maintenance:session-fd1753a572db47ca:31
- source_message_refs: message:25, message:26, message:27, message:28
