# Session Title
_A short and distinctive title for the session._
如果我之后再问复杂问题，你应该先怎么回答？

# Active Goal
_What is the user currently trying to achieve?_
- 我们这个项目现在优先抓哪条主线？

# Flow State
_What flow is currently active, and how confident is the system about it?_
- 当前流程类型：coding_change_flow
- 流程状态：awaiting_user
- 流程置信度：0.9
- 当前步骤：基于当前结果等待用户确认或继续下一步
- 下一步：继续处理当前用户请求：我们这个项目现在优先抓哪条主线？

# Context Slots
_Which contextual bindings are active for the current flow?_
- 当前规则：默认终端命令应该怎么写？

# Current Task State
_What is currently in progress or waiting to be done?_
- 当前关注的用户问题：我们这个项目现在优先抓哪条主线？
- 当前处理形态：code_change
- 最近产出：面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有知识库资料 → 用 `search_knowledge` 检索 - 需要外部信息...

# Warm Context
_Still-useful prior context from earlier in this session._
- 此前请求：我们这个项目现在优先抓哪条主线？
- 延续状态：当前关注的用户问题：我们这个项目现在优先抓哪条主线？
- 近期结论：当前主线：**优化 Memory 和 RAG**。 依据：长期记忆中已明确记录“我们项目当前主线是优化 Memory 和 RAG”，这是稳定的工作反馈，优先级最高。
- 此前请求：如果我之后再问复杂问题，你应该先怎么回答？

# Key User Requests
_Stable instructions or constraints from the user within this session._
- 我们这个项目现在优先抓哪条主线？
- 默认终端命令应该怎么写？
- 如果我之后再问复杂问题，你应该先怎么回答？

# Files and Functions
_Important files, modules, and functions relevant to the current work._
- SKILL.md

# Conventions and Constraints
_Commands, operating conventions, and environment constraints that matter now._
- 我们这个项目现在优先抓哪条主线？
- 当前主线：**优化 Memory 和 RAG**。 依据：长期记忆中已明确记录“我们项目当前主线是优化 Memory 和 RAG”，这是稳定的工作反馈，优先级最高。
- 默认终端命令应该怎么写？
- 默认终端命令采用 **Windows PowerShell 风格**。 示例对照： | 场景 | PowerShell 写法 | |------|------------------| | 查看文件列表 | `Get-ChildItem` 或 `ls` | | 删除文件 | `Remove-Item path` | | 复制文件 | `Copy-Item src dst` | | 查看内容 | `Get-Content file` | | 创建目录 | `New-Item -
- 面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有知识库资料 → 用 `search_knowledge` 检索 - 需要外部信息 → 用联网搜索或专用工具 4. **明确区分**：事实 vs 推断 vs 不确定项，不混在一起说。 5. **给可执行

# Errors and Corrections
_Failures, corrections, and approaches to avoid repeating._

# Decisions and Learnings
_Concrete conclusions, tradeoffs, and learnings established in this session._
- 当前主线：**优化 Memory 和 RAG**。 依据：长期记忆中已明确记录“我们项目当前主线是优化 Memory 和 RAG”，这是稳定的工作反馈，优先级最高。
- 面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有知识库资料 → 用 `search_knowledge` 检索 - 需要外部信息 → 用联网搜索或专用工具 4. **明确区分**：事实 vs 推断 vs 不确...

# Key Results
_Exact outputs, conclusions, or artifacts already produced for the user._
- 面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有知识库资料 → 用 `search_knowledge` 检索 - 需要外部信息 → 用联网搜索或专用工具 4. **明确区分**：事实 vs 推断 vs 不确定项，不混在一起说。 5. **给可执行

# Risk Watch
_Known risks in current session state and active safeguards._

# Next Step
_What the assistant should most likely do next if the work continues._
- 继续处理当前用户请求：我们这个项目现在优先抓哪条主线？

# Durable Candidates
_Potential long-term memories distilled from this session state._
- [preference/user] 默认终端命令应该怎么写？
- [work/project] 默认终端命令应该怎么写？
- [work/project] 默认终端命令采用 **Windows PowerShell 风格**。 示例对照： | 场景 | PowerShell 写法 | |------|------------------| | 查看文件列表 | `Get-ChildItem` 或 `ls` | | 删除文件 | `Remove-Item path` | | 复制文件 | `Copy-Item src dst` | | 查看内容 | `Get-Content file` | | 创建目录 | `New-Item -ItemType Directory -Path name` | | 环境变量 | `$env:VAR_NAME` | 如果需要跨平台兼容，可以在脚本中判断 `...
- [work/project] 面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有知识库资料 → 用 `search_knowledge` 检索 - 需要外部信息 → 用联网搜索或专用工具 4. **明确区分**：事实 vs 推断 vs 不确定项，不混在一起说。 5. **给可执行结论**：优先给出下一步能做什么，而不是空泛表态。 简单说：**先查再答，有据可依，给行动项**。
- [work/project] 当前主线：**优化 Memory 和 RAG**。 依据：长期记忆中已明确记录“我们项目当前主线是优化 Memory 和 RAG”，这是稳定的工作反馈，优先级最高。
- [work/project] 面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有知识库资料 → 用 `search_knowledge` 检索 - 需要外部信息 → 用联网搜索或专用工具 4. **明确区分**：事实 vs 推断 vs 不确...

# Worklog
_Short chronological bullets of meaningful events._
- user: 我们这个项目现在优先抓哪条主线？
- assistant: 当前主线：**优化 Memory 和 RAG**。 依据：长期记忆中已明确记录“我们项目当前主线是优化 Memory 和 RAG”，这是稳定的工作反馈，优先级最高。
- user: 默认终端命令应该怎么写？
- assistant: 默认终端命令采用 **Windows PowerShell 风格**。 示例对照： | 场景 | PowerShell 写法 | |------|------------------| | 查看文件列表 | `Get-ChildItem` 或 `ls` | | 删除文件 | `R...
- user: 如果我之后再问复杂问题，你应该先怎么回答？
- assistant: 面对复杂问题，我会按这个顺序处理： 1. **先确认目标**：用一句话澄清你想解决的核心问题是什么。 2. **先查上下文**：检查长期记忆、知识库、已有技能，看是否有现成答案或相关经验。 3. **再选路径**： - 有技能 → 读 `SKILL.md`，按技能流程执行 - 有...
