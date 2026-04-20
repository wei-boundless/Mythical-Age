# Project Profile

当前项目的高稳定性默认规则如下：

- 当前运行环境以 Windows PowerShell 为准，终端命令默认优先采用 PowerShell 风格。
- 多模态资料进入知识库前，先解析、清洗、切分，再做 embedding 和索引。
- 长期上下文按 `constitution -> profile -> durable memory -> session memory` 的顺序装配。
