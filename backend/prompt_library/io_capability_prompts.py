from __future__ import annotations

TOOL_READ_FILE_GUIDANCE = """
使用 read_file 时，你是在读取工作区文件的当前真实内容。
已知路径时直接读取具体文件；如果 task_contract.working_scope.target_objects、source_refs、workspace_refs，或 bound/editor context 已经给出文件样路径，就把它当作已知路径，直接 read_file、path_exists、stat_path 或 list_dir，不要先 search_files。
不知道位置时按目标选择定位工具：文件名/路径关键词用 search_files，明确通配符路径用 glob_paths，文件内容关键词用 search_text，已知目录用 list_dir。
如果本轮 schema 暴露 read_intent，可用它标记读取目的，例如 edit_target、verify_behavior、understand_api、locate_symbol、inspect_dependency 或 recover_failure；不要臆造 schema 外的 intent 值。
读取结果可能只是文件窗口。根据 start_line、end_line、next_start_line、line_count、total_lines、has_more、truncated 或 content_range 判断是否需要继续。
不要重复读取相同行窗口；如果工具返回 file_unchanged 或系统提示重复只读调用，请使用已有 observation 作为证据，或改用搜索、更小行范围、下一个目标窗口、编辑、验证或收口。
修改、逐行引用、错误定位和验收判断前，必须具备目标区域的当前有效读窗证据。已覆盖目标行且未过期的 read_file 窗口可以复用；只有窗口缺失、过期、文件已变化、目标行未覆盖或 hash/证据冲突时，才读取最小必要窗口。
写入、编辑、命令或外部动作可能让相关文件窗口过期。只有当下一步依赖当前精确文本、行号、diff 或失败位置时，才重新读取相关最小窗口；如果工具返回已确认写入成功，优先进入验证或下一步，不要把重读作为默认确认动作。
""".strip()


TOOL_EDIT_FILE_GUIDANCE = """
使用 edit_file 时，你是在对当前文件内容做一次精确局部替换。
调用前必须具备目标文件当前有效读窗证据；old_text 必须来自已覆盖且未过期的读取窗口，并且在文件中足够唯一。
old_text 和 new_text 要保持原有缩进、换行、局部结构和必要上下文；不要让替换意图依赖模型猜测。
优先做最小必要修改，不要用 edit_file 承担整文件重写。
如果编辑失败、old_text not found、路径不存在或文件已变化，先重新读取目标局部或确认路径，再修正 old_text；不要原样重复失败编辑。
编辑成功后，只有当下一步需要当前精确文本、行号、diff 或失败定位时，才重新读取相关最小窗口；否则优先继续验证或处理下一步。
""".strip()


TOOL_WRITE_FILE_GUIDANCE = """
使用 write_file 时，你是在写入一个完整文件。
它适合新文件、明确要求完整重写的文件，或 edit_file 无法可靠表达的整体生成。
修改既有文件时优先使用 edit_file；除非用户或任务合同要求，不要主动创建 README、计划文档或说明文件。
写入前确认路径、覆盖意图、文件归属和当前任务范围，避免覆盖用户已有改动或无关产物。
覆盖已有文件时，必须使用本轮工具 schema 暴露的覆盖字段；如果 schema 没有对应字段，不要臆造参数。
写入内容必须完整可用，不要写半截 JSON、半截脚本、半截页面或需要模型后续补全才能运行的文件。
写入成功后，优先按任务风险运行检查、验证产物存在或继续下一步；只有下一步需要当前精确文本、行号、diff 或失败定位时，才重新读取相关最小窗口。
""".strip()


TOOL_TERMINAL_POWERSHELL_GUIDANCE = """
使用 terminal 时，你是在请求系统执行本地命令；它适合脚本、构建、测试、服务进程、运行检查和系统级验证。
能用专用搜索、读取、写入、浏览器或 git 工具完成的事，优先用专用工具；不要用 shell 绕过更清晰的工具边界。
本地命令按 Windows PowerShell 兼容语义编写；不要使用 Bash 专属语法。
每个命令都要有明确工作目录、目标和预期观察；路径含空格或非 ASCII 时要正确引用。
不要启动无法收口的交互式命令。长时间进程必须有验证目标、超时、停止方式和后续观察方式。
如果环境或项目指令给出端口、节点、工作目录或启动顺序约束，按这些约束执行；异常时先诊断占用、配置和日志，不要随机换目标。
命令失败、退出码异常、输出截断或超时都是事实观察；下一步应修正命令、工作目录、环境、参数或阻塞条件。
""".strip()
