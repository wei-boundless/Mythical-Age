# Agent Guide

## 核心原则

1. 文件优先。会话、长期记忆、技能和知识都应该落在本地文件中。
2. 技能优先。若现有技能能解决问题，先读取对应 `SKILL.md` 再执行。
3. 透明优先。工具调用、检索结果和记忆注入都要尽量可解释。

## 工具使用协议

- `read_file`: 读取技能、工作区文档和知识文件。
- `terminal`: 仅在需要运行本地命令时使用。
- `python_repl`: 仅用于短脚本和数据处理。
- `fetch_url`: 获取网页或 JSON 接口内容。
- `search_knowledge`: 检索 `knowledge/` 下的资料。

## Long-Term Context 协议

- `context_profile/constitution/` 存放高稳定性的系统设定。
- `context_profile/profile/` 存放用户与项目的长期画像。
- `durable_memory/` 存放可召回、可整理的动态长期记忆。
- 未检索到的长期记忆不应被默认假设为仍然可用。
