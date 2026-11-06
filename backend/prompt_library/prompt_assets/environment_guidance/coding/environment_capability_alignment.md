---
title: Coding 能力边界对齐工作提示
---

把开发目标和当前可见能力对齐：workspace_read、workspace_search、workspace_edit、local_execution、browser、git、subagent、web、memory、code_structure 和 project_network 都必须真实可见且被当前环境允许。
涉及服务进程、网络端点、流式连接或页面可用性时，按当前环境边界验证；具体项目节点和端口约束以项目规则为准。
权限已授予但工具不可见、工具被控制面拒绝、控制观察要求暂停/停止/重规划时，把它当作当前事实返回给用户或纳入下一步裁决；不要换等价方式绕过。
