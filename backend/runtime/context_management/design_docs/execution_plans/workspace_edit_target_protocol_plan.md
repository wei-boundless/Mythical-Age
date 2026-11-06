# Workspace Edit Target Protocol

## 目标

将 `workspace_read` 与 `workspace_edit` 的文件修改链路统一为“读取证据 + 精确目标 + 版本校验 + 原子提交”。保留现有工具外层契约：

- `workspace_read(action=...)`
- `workspace_edit(action=...)`

不新增平行工具调用，不保留 `old_text` 编辑主链路，不使用正文去重或猜测式补丁。

## 正式目标模型

读取结果提供 `edit_target`。目标对象包含：

- `observation_ref`：读取证据引用；
- `path` 与 `repository_id`：目标资源身份；
- `start_line`、`start_column`、`end_line`、`end_column`：可读范围；
- `start_byte`、`end_byte`：实际替换范围；
- `base_sha256`：读取时的整个文件版本；
- `range_sha256`：目标范围版本；
- `mtime_ns`：快速版本检查。

目标对象不包含版本后缀。目标句柄由系统生成，Agent 只引用它，不计算哈希、不复现旧文本。

## 工具契约

`workspace_edit(action=edit)` 接受 `target` 与 `new_text`。

`workspace_edit(action=batch_edit)` 接受一个文件版本和多个独立目标；系统按数组下标返回失败项。所有目标通过预检后一次性写回；任一目标失败则整批不写入。

`workspace_read(action=file)` 保留现有读取参数，并可通过范围、符号或受限匹配定位目标。定位只产生候选目标，不直接执行写入。

正式编辑参数删除 `old_text`。编辑执行器根据目标引用取得当前内容并完成版本校验。

## 执行边界

1. 读取证据必须覆盖目标范围。
2. 当前文件版本必须匹配 `base_sha256` 或等价版本事实。
3. 当前目标范围必须匹配 `range_sha256`。
4. 实际替换使用 UTF-8 字节区间，行列信息用于可读性和诊断。
5. 目标不明确、范围重叠、编码不稳定或版本变化时拒绝写入。
6. 成功后返回新的文件版本和新的可复用目标。

## 错误协议

统一返回结构化错误：

- `invalid_edit_target`
- `target_outside_observation`
- `target_not_found`
- `target_ambiguous`
- `target_range_changed`
- `target_version_conflict`
- `target_encoding_conflict`
- `target_overlap`
- `batch_edit_validation_failed`
- `write_commit_failed`

每个错误提供 `retryable`、期望版本、实际版本、候选范围和可执行的 `repair_instruction`，并明确是否产生写入。

## 系统对接

以下边界必须使用同一个目标模型：

- `runtime.tool_runtime.native_tools`
- `runtime.tool_runtime.read_file_window`
- `capability_system.tools.native_tool_catalog`
- `capability_system.tools.tool_surface`
- `file_management.gateway`
- `file_management.service`
- `WorkspaceFileService`
- 文件状态与 observation artifact
- 权限审批指纹
- 工具结果 envelope
- 前端工具反馈

审批指纹绑定工具、动作、路径、仓库、文件版本、目标身份和批次编辑身份，不能跨版本复用。

## Agent 提示约束

Agent 必须先读取目标，再引用读取结果中的目标身份。Agent 不得自行构造旧文本、哈希、字节偏移或目标身份。版本冲突必须重新读取；目标歧义必须缩小范围；批量编辑必须逐条提供独立目标。

## 实施顺序

1. 扩展读取结果和 observation artifact，生成目标信息。
2. 修改单条编辑执行器，移除 `old_text`，接入目标解析和版本校验。
3. 修改批量编辑执行器，逐条预检、重叠检查和一次写回。
4. 统一文件网关、服务层和权限指纹。
5. 更新工具注册、schema、提示和错误 envelope。
6. 更新前端工具反馈和结果展示。
7. 清理旧编辑分支和过时字段。
8. 使用真实文件执行单词、单行、多行、批量、版本冲突、歧义和编码边界验证。

## 验收标准

- 读取 50 行只修改其中一个词时，实际写入范围只包含该词。
- 文件被外部修改后旧目标不能写入。
- 批量任一目标失败时文件内容完全不变。
- 成功写入后可继续引用新的目标身份。
- 错误反馈能够指导 Agent 重新读取并恢复。
- 工具外层名称与 `action` 结构保持不变。
