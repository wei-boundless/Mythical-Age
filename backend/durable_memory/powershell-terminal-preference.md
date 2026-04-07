---
schema_version: durable-memory.v2
title: 终端命令优先使用 PowerShell 语法
summary: 当前运行环境是 Windows PowerShell，终端命令默认优先采用 PowerShell 风格。
canonical_statement: 当前运行环境是 Windows PowerShell，终端命令默认优先采用 PowerShell 风格。
type: workflow
memory_class: work
tags: [workflow, terminal, powershell, windows]
retrieval_hints: [PowerShell, Windows 终端, 终端语法约定, 命令风格]
created_at: 2026-04-05T00:00:00+00:00
updated_at: 2026-04-06T00:00:00+00:00
created_by: manual
source_session_id:
source_role: user
source_message_excerpt: 当前项目运行环境是 Windows PowerShell，终端命令优先采用 PowerShell 风格。
confidence: high
status: active
last_confirmed_at: 2026-04-05T00:00:00+00:00
---

## Canonical Memory

当前项目运行环境是 Windows PowerShell。
在终端操作中，默认优先使用 PowerShell 风格命令，例如：

- `Get-ChildItem`
- `Get-Content`
- `Test-Path`
- `Select-String`

## Retrieval Hints

- PowerShell
- Windows 终端
- 终端语法约定
- 命令风格

## Why Stored

这是稳定的环境与工作流约定。后续生成终端命令时，应尽量避免默认输出 bash 风格命令。

## Source Evidence

当前项目运行环境是 Windows PowerShell，终端命令优先采用 PowerShell 风格。
