# Session Title
_A short and distinctive title for the session._
如果我马上问复杂问题，你该先怎么组织回答？

# Active Goal
_What is the user currently trying to achieve?_
- 我们项目现在优先做什么？

# Flow State
_What flow is currently active, and how confident is the system about it?_
- 当前流程类型：coding_change_flow
- 流程状态：awaiting_user
- 流程置信度：0.45
- 当前步骤：基于当前结果等待用户确认或继续下一步
- 下一步：先向用户澄清当前目标，再决定是否切换流程：我们项目现在优先做什么？

# Context Slots
_Which contextual bindings are active for the current flow?_
- 当前规则：默认终端命令应该用什么？

# Current Task State
_What is currently in progress or waiting to be done?_
- 当前关注的用户问题：我们项目现在优先做什么？
- 最近产出：先给结论，再展开解释。 这是你之前明确沉淀的偏好，已记录在长期记忆中。

# Warm Context
_Still-useful prior context from earlier in this session._
- 此前请求：我们项目现在优先做什么？
- 延续状态：当前关注的用户问题：我们项目现在优先做什么？
- 近期结论：默认终端命令应该用 PowerShell 风格。 这是项目配置中明确规定的：当前运行环境以 Windows PowerShell 为准，终端命令默认优先采用 PowerShell 风格。
- 此前请求：如果我马上问复杂问题，你该先怎么组织回答？

# Key User Requests
_Stable instructions or constraints from the user within this session._
- 我们项目现在优先做什么？
- 默认终端命令应该用什么？
- 如果我马上问复杂问题，你该先怎么组织回答？

# Files and Functions
_Important files, modules, and functions relevant to the current work._

# Conventions and Constraints
_Commands, operating conventions, and environment constraints that matter now._
- 我们项目现在优先做什么？
- 默认终端命令应该用什么？
- 默认终端命令应该用 PowerShell 风格。 这是项目配置中明确规定的：当前运行环境以 Windows PowerShell 为准，终端命令默认优先采用 PowerShell 风格。

# Errors and Corrections
_Failures, corrections, and approaches to avoid repeating._
- 低置信度流程切换已降级处理，等待进一步澄清。

# Decisions and Learnings
_Concrete conclusions, tradeoffs, and learnings established in this session._
- 默认终端命令应该用 PowerShell 风格。 这是项目配置中明确规定的：当前运行环境以 Windows PowerShell 为准，终端命令默认优先采用 PowerShell 风格。
- 先给结论，再展开解释。 这是你之前明确沉淀的偏好，已记录在长期记忆中。

# Key Results
_Exact outputs, conclusions, or artifacts already produced for the user._
- 先给结论，再展开解释。 这是你之前明确沉淀的偏好，已记录在长期记忆中。

# Risk Watch
_Known risks in current session state and active safeguards._
- Flow confidence is low; keep state conservative and verify user intent before major shifts.
- Potential flow switch was downgraded because understanding confidence is too low.

# Next Step
_What the assistant should most likely do next if the work continues._
- 先向用户澄清当前目标，再决定是否切换流程：我们项目现在优先做什么？
- 继续处理当前用户请求：我们项目现在优先做什么？

# Worklog
_Short chronological bullets of meaningful events._
- user: 我们项目现在优先做什么？
- assistant: 根据长期记忆中的记录，我们项目当前主线是优化 Memory 和 RAG。 这是之前明确沉淀下来的工作重点。如果你需要，我可以进一步： - 梳理 Memory 和 RAG 各自的优化方向和待办事项 - 查看是否有更细粒度的任务记录或进展状态 需要我展开吗？
- user: 默认终端命令应该用什么？
- assistant: 默认终端命令应该用 PowerShell 风格。 这是项目配置中明确规定的：当前运行环境以 Windows PowerShell 为准，终端命令默认优先采用 PowerShell 风格。
- user: 如果我马上问复杂问题，你该先怎么组织回答？
- assistant: 先给结论，再展开解释。 这是你之前明确沉淀的偏好，已记录在长期记忆中。
