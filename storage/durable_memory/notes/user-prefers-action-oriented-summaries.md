---
schema_version: durable-memory.v3
title: 用户偏好行动导向的总结输出及交互约定
summary: 用户要求报告结论以行动建议形式输出，每条带行动动词，面向业务负责人汇报场景。复杂问题结论前置再补依据。称呼用户为'岩'。信息不足时先明确说缺什么不直接猜。
canonical_statement: 用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置再补依据，称呼用户为'岩'，信息不足时先明确说缺什么不直接猜。
type: user
memory_class: preference
tags: [user, preference, 用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置再补依据，称呼用户为'岩'，信息不足时先明确说缺什么不直接猜。, 用户偏好行动导向的总结输出及交互约定, 用户要求报告结论以行动建议形式输出，每条带行动动词，面向业务负责人汇报场景。复杂问题结论前置再补依据。称呼用户为'岩'。信息不足时先明确说缺什么不直接猜。, 用户偏好]
retrieval_hints: [用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置再补依据，称呼用户为'岩'，信息不足时先明确说缺什么不直接猜。, 用户偏好行动导向的总结输出及交互约定, 用户要求报告结论以行动建议形式输出，每条带行动动词，面向业务负责人汇报场景。复杂问题结论前置再补依据。称呼用户为'岩'。信息不足时先明确说缺什么不直接猜。, 用户偏好, 输出格式, 行动建议, 结论前置, 称呼岩]
created_at: 2026-05-19T21:41:32+00:00
updated_at: 2026-05-19T22:42:31+00:00
created_by: agent:1
source_session_id: 71166e9aaa0f42038f5bfe1a10d3b8bb
source_role: conversation
source_message_excerpt: message:32 用户说'记住：以后复杂问题先给结论。' message:33 助手确认'记住了。以后复杂问题：结论前置，再补依据。' message:34 用户说'记住：回答我时可以直接称呼我岩。' message:35 助手确认'记住了，岩。'
confidence: high
status: active
last_confirmed_at: 2026-05-19T22:42:31+00:00
scope: project
stability: stable
source_kind: memory_maintenance_agent
eligible_for_injection: true
review_after: 
supersedes: 
invalidation_reason: 
---

## Canonical Memory
用户在处理报告分析任务时，明确要求将结论压成带行动动词的行动建议，偏好面向业务/管理层的简洁、可执行输出格式。此外，用户要求复杂问题结论前置再补依据，称呼用户为'岩'，信息不足时先明确说缺什么不直接猜。

## Why Stored
用户在本轮对话中明确提出了两个新的交互约定：复杂问题结论前置、称呼用户为'岩'。这些是稳定的用户偏好，跨会话仍有价值，需要更新到已有的用户偏好记忆中。

## How To Apply
以后回答复杂问题时，先给出简洁结论再补充依据；直接称呼用户为'岩'；信息不足时先明确说缺什么不直接猜；报告类输出优先使用行动建议格式。

## Source Evidence
message:32 用户说'记住：以后复杂问题先给结论。' message:33 助手确认'记住了。以后复杂问题：结论前置，再补依据。' message:34 用户说'记住：回答我时可以直接称呼我岩。' message:35 助手确认'记住了，岩。'

## Maintenance Receipt
- run_id: memory-maintenance:83b377a5489b490490b0708257ed9c44:36
- source_message_refs: message:32, message:33, message:34, message:35
