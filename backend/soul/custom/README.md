# Custom Souls

这里用于放用户自制灵魂。

建议结构：

```text
backend/soul/custom/
  <soul_id>/
    SOUL.md
    profile.json
    portrait.png
```

自制灵魂可以定义身份、背景、语言风格、工作习惯、任务偏好和协作姿态。

自制灵魂不能定义：

- 工具权限。
- worker route。
- memory 写入权。
- ControlKernel 调度权。
- 覆盖 `CORE.md` 的规则。

这些权限后续统一由 `ControlKernel / ResourcePolicy / RuntimeDirective` 管理。
