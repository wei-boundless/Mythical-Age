# mythical agent Apifox 接口文档导入说明

## 导入文件

- OpenAPI 文件：`docs/接口文档/apifox-openapi.json`
- Apifox 显示名称：`mythical agent`
- 接口来源：`backend/app.py` 实际注册的 FastAPI 路由
- 后端本地环境：`http://127.0.0.1:8003`
- 前端 API Base：`http://127.0.0.1:8003/api`

## Apifox 导入方式

1. 打开 Apifox，进入目标项目。
2. 选择「导入数据」或「导入 OpenAPI/Swagger」。
3. 选择本文件：`docs/接口文档/apifox-openapi.json`。
4. 导入后确认环境 Base URL 为：`http://127.0.0.1:8003`。

## 接口分组统计

| 分组 | 接口数量 |
| --- | ---: |
| tasks | 50 |
| health-system | 28 |
| memory | 18 |
| orchestration-catalog | 16 |
| sessions | 15 |
| orchestration-harness | 12 |
| capability-system | 11 |
| config | 10 |
| orchestration | 10 |
| code-environment | 8 |
| chat | 6 |
| mcp-system | 6 |
| runtime-monitor | 5 |
| files | 4 |
| tokens | 4 |
| image-assets | 2 |
| 未分组 | 1 |

总计：178 个 path，206 个 operation。

## 注意事项

- `/health` 是根级健康检查接口，不带 `/api` 前缀。
- 其余业务接口由 `backend/app.py` 统一挂载到 `/api` 前缀下。
- 文档由 FastAPI OpenAPI 生成器导出，请以该 JSON 为 Apifox 的主导入文件。
