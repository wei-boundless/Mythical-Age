# Session Title
_A short and distinctive title for the session._
如果我之后再问复杂问题，你应该先怎么回答？

# Active Goal
_What is the user currently trying to achieve?_
- 我们这个项目现在优先抓哪条主线？

# Flow State
_What flow is currently active, and how confident is the system about it?_
- 当前流程类型：coding_change_flow
- 流程状态：blocked
- 流程置信度：0.35
- 当前步骤：修复当前阻塞并恢复主流程
- 下一步：继续处理当前用户请求：我们这个项目现在优先抓哪条主线？

# Context Slots
_Which contextual bindings are active for the current flow?_
- 当前规则：默认终端命令应该怎么写？

# Current Task State
_What is currently in progress or waiting to be done?_
- 当前关注的用户问题：我们这个项目现在优先抓哪条主线？
- 最近问题：Request failed: 模型服务暂时不可用，请稍后重试。

# Warm Context
_Still-useful prior context from earlier in this session._
- 此前请求：我们这个项目现在优先抓哪条主线？
- 延续状态：当前关注的用户问题：我们这个项目现在优先抓哪条主线？
- 此前请求：如果我之后再问复杂问题，你应该先怎么回答？

# Key User Requests
_Stable instructions or constraints from the user within this session._
- 我们这个项目现在优先抓哪条主线？
- 默认终端命令应该怎么写？
- 如果我之后再问复杂问题，你应该先怎么回答？

# Files and Functions
_Important files, modules, and functions relevant to the current work._

# Conventions and Constraints
_Commands, operating conventions, and environment constraints that matter now._
- 我们这个项目现在优先抓哪条主线？
- 默认终端命令应该怎么写？

# Errors and Corrections
_Failures, corrections, and approaches to avoid repeating._
- Request failed: 模型服务暂时不可用，请稍后重试。

# Decisions and Learnings
_Concrete conclusions, tradeoffs, and learnings established in this session._

# Key Results
_Exact outputs, conclusions, or artifacts already produced for the user._

# Risk Watch
_Known risks in current session state and active safeguards._
- Flow confidence is low; keep state conservative and verify user intent before major shifts.
- Recent turns contain repeated error events; prioritize unblock and recovery step.

# Next Step
_What the assistant should most likely do next if the work continues._
- 继续处理当前用户请求：我们这个项目现在优先抓哪条主线？

# Worklog
_Short chronological bullets of meaningful events._
- user: 我们这个项目现在优先抓哪条主线？
- assistant: Request failed: 模型服务暂时不可用，请稍后重试。
- user: 默认终端命令应该怎么写？
- user: 如果我之后再问复杂问题，你应该先怎么回答？
