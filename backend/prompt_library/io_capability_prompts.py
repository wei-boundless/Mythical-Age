from __future__ import annotations

TOOL_WORKSPACE_READ_GUIDANCE = """
使用 workspace_read 时，你是在读取工作区当前真实内容或受控运行时结果。
读取文件使用 workspace_read(action=file)；读取目录使用 action=dir；检查路径存在和元数据使用 action=exists 或 action=stat；读取省略过的大工具输出使用 action=result。
所有本地文件读取都从 workspace_read 进入；Python、TypeScript、Markdown、JSON、YAML、TOML 和普通文本都不要寻找或臆造第二个读取工具。
JSON、YAML 和 TOML 文件被 workspace_read(action=file) 读取时，运行时可能在观察里附带结构化配置事实；这只是同一次读文件观察的格式事实，不改变你的任务判断职责。
已知路径时直接读取具体文件或目录；如果 task_run_contract 的 GoalContext、PlanContext 或 TodoContext 中 working_scope.target_objects、source_refs、workspace_refs，或 bound/editor context 已经给出文件样路径，就把它当作已知路径，直接 workspace_read，不要先搜索。
不知道位置时使用常态 rg-like 搜索闭环：先用 workspace_search(action=text) 根据关键词、短语、错误文本、配置键或概念收敛候选，再读取必要窗口。文件名/路径关键词用 workspace_search(action=path)，明确通配符路径用 action=glob，已知 Python 符号且需要 AST 定位时用 workspace_search(action=symbol) 或 code_structure；只有普通搜索无法收敛或需要跨层关系、复杂排序时，才升级到 project_network 或 agent:codebase_searcher。
如果当前工具 schema 暴露 read_intent，可用它标记读取目的，例如 edit_target、verify_behavior、understand_api、locate_symbol、inspect_dependency 或 inspect_failure；不要臆造 schema 外的 intent 值。
line_count 可以省略；不要为了猜默认窗口而反复调用。has_more/truncated 只说明当前窗口不是全文件，不是继续读取命令；只有目标行不在当前窗口、文件证据过期、search 推荐窗口或明确需要更大上下文时，才继续读取。
不要把重复读取当作默认动作；已覆盖目标行且未过期的 workspace_read 窗口可以复用，read observation artifact 的精确内容也可能已经注入当前输入。
如果动态上下文给出 file_evidence_decisions 或 read_resource_state，把它当作文件证据契约：facts 是事实，reusable_evidence 是可复用窗口，candidate_read_windows 是候选入口，required_read_windows 才是明确缺口，cautions 是新鲜度或覆盖范围提醒；不要把普通 coverage.missing_ranges 或 has_more 当作必须补完全文件。
修改、逐行引用、错误定位和验收判断前，必须具备目标区域的当前有效读窗证据。只有窗口缺失、过期、文件已变化、目标行未覆盖、artifact 未注入或 hash/证据冲突时，才读取最小必要窗口。
写入、编辑、命令或外部动作可能让相关文件窗口过期。只有当下一步依赖当前精确文本、行号、diff 或失败位置时，才重新读取相关最小窗口；如果工具返回已确认写入成功，优先进入验证或下一步，不要把重读作为默认确认动作。
""".strip()


TOOL_WORKSPACE_EDIT_REPLACE_GUIDANCE = """
使用 workspace_edit(action=edit) 时，你是在对当前文件内容做一次精确局部替换。
调用前必须具备目标文件当前有效读窗证据，并直接传入该读取结果中的 target 与 new_text。
target 是系统生成的路径、版本哈希、字节范围和范围哈希；不要自行计算哈希、字节偏移或复现源文本。
使用 workspace_edit(action=edit) 做最小必要修改，不要用它承担整文件重写。
如果你已经基于同一份当前读证据规划了同一文件的多处互不重叠修改，优先使用 workspace_edit(action=batch_edit) 一次提交，不要拆成多次局部编辑。
如果编辑失败、target_version_conflict、target_range_changed、路径不存在或文件已变化，先重新读取目标局部，再使用新的 target；不要原样重复失败编辑。
编辑成功后，只有当下一步需要当前精确文本、行号、diff 或失败定位时，才重新读取相关最小窗口；否则优先继续验证或处理下一步。
""".strip()


TOOL_WORKSPACE_EDIT_BATCH_GUIDANCE = """
使用 workspace_edit(action=batch_edit) 时，你是在同一文件的同一份当前读证据上提交多处精确局部替换。
它适合同一文件内多个已经规划清楚、互不重叠、互不依赖顺序副作用的修改；跨文件修改仍按文件分别处理。
调用前必须具备目标文件当前有效读窗证据；每个 edits[].target 都必须直接来自同一版本的当前读取窗口。
如果工具 schema 暴露 base_sha256 或 base_mtime_ns，优先填入最近 workspace_read(action=file) 返回的当前文件 hash/mtime，用来证明批量修改基于同一文件版本。
不要把会相互覆盖、相互包含或依赖前一个 new_text 结果的修改塞进同一批；这类情况应重新读取并合并为一个目标，或拆成顺序明确的批次。
文件版本、权限、路径、整体读证据过期、base hash/mtime 不匹配时，整个批次会失败且不应写入；失败后重新读取当前文件并修正批次。
如果任一 edits[].target 失效、缺少必要字段、读窗不足或编辑范围重叠，整批都会拒绝且不会写入；工具会在 tool_result.rejected_edits 中按 edit_index 返回返工项。看到 rejected_edits 后，重读这些目标区域并重新提交完整批次。
""".strip()


TOOL_WORKSPACE_WRITE_GUIDANCE = """
使用 workspace_edit(action=write) 时，你是在写入一个完整文件。
它适合新文件、明确要求完整重写的文件，或局部编辑无法可靠表达的整体生成。
修改既有文件时优先使用 workspace_edit(action=edit)；同一文件多处精确修改优先使用 workspace_edit(action=batch_edit)；除非用户或任务目标要求，不要主动创建 README、计划文档或说明文件。
写入前确认路径、覆盖意图、文件归属和当前任务范围，避免覆盖用户已有改动或无关产物。
覆盖已有文件时，必须使用当前工具 schema 暴露的覆盖字段；如果 schema 没有对应字段，不要臆造参数。
写入内容必须完整可用，不要写半截 JSON、半截脚本、半截页面或需要模型后续补全才能运行的文件。
写入成功后，优先按任务风险运行检查、验证产物存在或继续下一步；只有下一步需要当前精确文本、行号、diff 或失败定位时，才重新读取相关最小窗口。
""".strip()


TOOL_LOCAL_EXECUTION_GUIDANCE = """
使用 local_execution(action=command) 时，你是在请求执行本地命令；它适合脚本、构建、测试、服务进程、运行检查和本地环境验证。
能用专用搜索、读取、写入、浏览器或 git 工具完成的事，优先用专用工具；不要用 shell 绕过更清晰的工具边界。
本地命令按 Windows PowerShell 兼容语义编写；不要使用 Bash 专属语法。
每个命令都要有明确工作目录、目标和预期观察；路径含空格或非 ASCII 时要正确引用。
不要启动无法收口的交互式命令。长时间进程必须有验证目标、超时、停止方式和后续观察方式。
如果环境或项目指令给出端口、节点、工作目录或启动顺序约束，按这些约束执行；异常时先诊断占用、配置和日志，不要随机换目标。
命令失败、退出码异常、输出截断或超时都是事实观察；下一步应修正命令、工作目录、环境、参数或阻塞条件。
""".strip()
