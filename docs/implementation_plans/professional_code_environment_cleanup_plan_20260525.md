# 专业模式代码环境清理计划

日期：2026-05-25

## 1. 架构裁决

用户主交互模式只保留三种：

- 角色模式
- 标准模式
- 专业模式

代码修改、运行、验证、环境诊断、可选 Pi sidecar 检查，都属于专业模式下的复杂任务处理能力，不再拥有独立模式、独立 lane、独立 recipe 或独立任务域路由。

任务域只负责保存、分类和管理任务，不负责选择 runtime。

## 2. 清理范围

生产代码中只保留：

- `professional_mode`
- `professional_task`
- `runtime.recipe.professional_task`
- `backend/code_environment/*`
- `/api/code-environment/*`
- 前端 `code-environment` 工作台视图

需要清理的旧残留类型：

- 旧模式别名和旧 runtime route。
- 旧 lane、旧 recipe、旧 prompt resource。
- 旧 API 包名、旧前端类型名、旧 CSS class。
- 旧计划文档中把代码环境描述为第四模式的正向方案。
- 编译缓存中已经删除源码对应的旧 pyc。

## 3. 完成标准

- 活跃后端、前端、配置和 orchestration/prompt 存储中不再出现旧代码模式标识。
- 主页面模式集合仍为角色、标准、专业三种。
- 专业模式继续拥有代码任务需要的文件、git、shell、浏览器和验证能力。
- 代码环境页面只表达环境诊断，不负责模式选择或任务编排。
- 相关后端回归、前端类型检查、前端测试和页面验证通过。

## 4. 验证矩阵

- 后端编译：`python -m py_compile`
- 后端回归：interaction mode、professional runtime、orchestration agent management、prompt library、understanding runtime。
- 前端类型：`npx tsc --noEmit`
- 前端测试：`npm test -- --run`
- 浏览器验证：本地 Edge 打开 `http://127.0.0.1:3000/?view=code-environment`，确认标题为“专业模式代码环境”，页面没有旧模式可见文案。
