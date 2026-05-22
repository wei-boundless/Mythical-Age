# Runtime 配置页回归计划 - 2026-05-23

## 背景

上一版新增了独立 `SystemConfigView`，绕开了既有 `runtime_config_console_payload()` 与 `/config/runtime-console` 配置体系。这不符合项目现有结构，也让配置页形成了第二套保存入口。

## 目标

1. 配置页继续使用旧的 runtime console 数据模型：后端负责声明配置组、字段、状态和保存规则，前端只做通用渲染。
2. 生图模型配置纳入 runtime console，作为正式配置组保存到 `runtime_config.soul_image_assets`。
3. 删除前端独立读取/保存文本模型与生图模型的页面逻辑，避免两套配置页面并存。
4. UI 保持清晰、低噪音：配置组用分层导航切换，单页只展示当前配置组字段，不再铺开成多张大卡。
5. 补充回归测试，确认生图配置可以通过旧 runtime console 保存，并且密钥不会泄露。

## 实施步骤

1. 后端：在 `runtime_config_console_payload()` 加入 `soul_image_assets` 配置组，并在 `set_runtime_config_group()` 中支持保存。
2. 前端：重写 `SystemConfigView` 为 `RuntimeConfigConsole` 通用渲染器，使用 `getRuntimeConfigConsole()` 与 `setRuntimeConfigGroup()`。
3. 清理：移除 `SystemConfigView` 中对独立模型配置接口的依赖，删除不再使用的 API helper 和多余样式。
4. 验证：更新后端测试，运行配置回归测试与前端构建。
