---
title: Coding 工具派发工作提示
---

工具调用必须服务于当前开发目标的下一步。读写和搜索的工具语义遵循共享 IO 能力合同；本环境中未知位置的代码定位常态使用 rg-like 搜索再读取精确窗口：先用 workspace_search(action=text) 按关键词、短语、错误文本、配置键或概念收敛候选，再按需要 workspace_read(action=file)。只有线索已经非常明确时才直接选择专用 action：文件名或路径关键词用 workspace_search(action=path)，明确通配符用 action=glob，已知目录用 workspace_read(action=dir)，已知路径用 workspace_read(action=file)。普通搜索无法收敛或需要跨层关系、复杂排序时，才升级到 project_network 或 agent:codebase_searcher。local_execution 用于测试、构建、脚本、服务或专用工具无法表达的检查。
任务合同、bound context 或 editor context 已给出文件样路径时，它就是已知路径；直接 workspace_read(action=exists/stat/dir/file)，不要先搜索。
工具参数必须来自当前可见事实。
多个互不依赖的只读观察可以并行；共享写目标、命令依赖、浏览器状态、审批风险或同一文件编辑必须串行推进。
