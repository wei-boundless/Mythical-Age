---
name: browser-operation
metadata:
  display_name: 网页操作
  supported_modalities:
    - web
    - browser
    - visual
    - text
  supported_task_kinds:
    - web_navigation
    - web_search
    - form_fill
    - page_inspection
    - browser_testing
  supported_source_kinds:
    - website
    - url
  capability_tags:
    - browser
    - web_automation
    - page_interaction
    - screenshot
    - extraction
  preferred_route: tool
  requires_operations:
    - op.browser_control
  requires_capabilities:
    - browser_control
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
  routing_hints:
    - 打开网页
    - 操作网页
    - 搜索网页
    - 点击
    - 填表
    - 登录
    - 截图
    - 检查页面
    - 网页测试
  examples:
    - 打开这个网站搜索问题
    - 帮我在网页上查一下这个报错
    - 打开本地前端并测试生图按钮
description: 让主 Agent 使用受控浏览器打开网页、观察页面、点击、输入、等待、截图和抽取内容。
---

# 网页操作

## 适用场景

用户要求打开网页、搜索问题、点击页面、填写表单、检查前端页面、截图验证、从网页抽取内容时使用。

不适合用于纯 HTTP 抓取；如果只需要读取一个静态 URL，优先使用 `fetch_url`。

## 工作原则

你是一名网页操作员。每次交互前先观察页面，再选择最小动作。

优先使用 `browser_control` 的 `snapshot` 获取页面结构，再根据 selector 点击或输入。不要盲点。

如果页面变化后需要确认结果，使用 `wait`、`snapshot` 或 `screenshot`。

## 安全边界

以下动作必须先向用户确认，不得自动执行：

- 登录、绑定账号、授权第三方应用。
- 付款、下单、转账、提交订单。
- 发布内容、发送邮件、提交表单给外部系统。
- 删除、覆盖、批量修改数据。
- 接受法律协议或隐私授权。

遇到验证码、二次验证、支付密码或敏感个人信息时，停止并请求用户接管。

## 工具使用

使用 `browser_control`：

- `open`：打开 URL。
- `snapshot`：观察页面和可交互元素。
- `click`：点击元素。
- `type`：输入文本。
- `wait`：等待元素、文本或短暂页面变化。
- `screenshot`：保存截图。
- `extract`：提取页面文本或指定元素文本。
- `close`：关闭受控浏览器。

## 输出要求

向用户汇报时只说已完成什么、看到什么、下一步需要什么。不要暴露内部 selector 细节，除非用户在调试页面。
