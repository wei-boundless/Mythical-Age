# 健康系统

日期：2026-05-04

## 定位

`backend/health_system` 是全项目的健康治理系统。

它不只是问题台账或诊断入口，还正式负责：

- issue / report / command / receipt 的健康治理主链
- verification gate 与健康工作台
- 测试治理
- regression harness
- trace / replay / experiment 观测链路

## 当前目录

- `registry.py`
  健康系统主注册表与治理入口
- `verification_service.py`
  健康验证与 gate 逻辑
- `workbench.py`
  健康工作台聚合视图
- `maintenance/`
  健康维护子域

## maintenance 子域

`maintenance/` 现在统一承接原先散落在系统外部的健康维护能力：

- `maintenance/test_system`
  测试语义、case registry、assertion、runtime loop 监控投影
- `maintenance/harness`
  回归执行、结果持久化、报告生成
- `maintenance/experiments`
  trace、turn artifact、prompt manifest、memory trace、编排回放快照

这意味着测试、harness、trace、experiment 不再被视为并列主系统，而是健康系统内部的维护能力。

## 对外入口

当前对外 API 统一挂在：

- `/api/health-system/*`
- `/api/health-system/maintenance/test-system/*`
- `/api/health-system/maintenance/experiments/*`

不再保留独立的 `/api/test-system/*` 或 `/api/experiments/*` 系统入口。
