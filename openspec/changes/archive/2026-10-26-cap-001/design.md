## Context

动机和业务边界见 proposal.md，验收行为见两份 delta specs。仓库尚无应用代码；用户指定 Python、PostgreSQL、React 和现有 kind 集群。文档可中文，全部产品 UI 文案为英文。当前阶段只创建规划文件。

## Goals / Non-Goals

**Goals:**
- 通过单个 API 服务和单个数据库完成 CRUD，避免引入异步任务和分布式组件。
- 使用数据库约束保障资产唯一性，确保重启后数据可用。
- 提供可重复的迁移、镜像构建和 kind 部署流程。

**Non-Goals:**
- 首版不建硬件部件明细表、账号体系、设备通信或审计系统。
- 不设计跨集群容灾、数据库高可用或公网访问方案。

## Decisions

### 1. 单体 API 与独立 React 前端

后端采用 FastAPI，数据层采用 SQLAlchemy、PostgreSQL 驱动和 Alembic 迁移；前端采用 React、TypeScript、Vite。此处是新项目的设计选择，不依赖特定最新版本；实施时选用兼容的稳定版本并锁定依赖。

相较 Django 全栈，此方案便于围绕简单 REST 契约组织前后端；相较微服务，单体 API 减少本地部署组件。目录约定为 `apps/backend/`、`apps/frontend/`、`infra/k8s/`，脚本放 `scripts/`。

```text
Browser → localhost port-forward → Frontend Service → Nginx
                                                       ├─ /      → React assets
                                                       └─ /api   → API Service → FastAPI
                                                                                    │
                                                                              PostgreSQL Service
                                                                                    │
                                                                              PostgreSQL → PVC
```

前端镜像用 Nginx 提供静态文件与 SPA 路由回退，并将 `/api` 原路径代理到后端。同源入口省去浏览器跨域配置；相较安装 Ingress 控制器，port-forward 更适合已有本地集群。开发模式可通过 Vite 代理访问 API。

### 2. 数据模型与校验

使用一张 `physical_servers` 表：UUID 主键；`name`、`service_tag`、`model` 必填；`management_ip`、`idrac_ip`、`lab`、`rack`、`rack_unit`、`cpu_summary`、`memory_summary`、`disk_summary`、`owner`、`purpose`、`notes` 可空；`status` 默认 `available`；时间戳使用带时区的 UTC 时间。

Service Tag 入库前去空白并转大写，数据库使用 UNIQUE 约束；状态采用字符串及 CHECK 约束。IP 字段由 API 验证 IPv4/IPv6。可选空字符串统一转为 null；名称、型号、Service Tag 去首尾空白并拒绝空值。普通短文本上限 255 字符，Service Tag 上限 64 字符，配置摘要和用途上限 2000 字符，备注上限 10000 字符，超限返回 422。数据库字段长度与约束保持一致。

硬件采用文本摘要以容纳不同配置写法，暂不建逐磁盘和逐内存明细表；位置字段保持自由文本，暂不建实验室和机柜字典。Service Tag 作为业务标识，UUID 作为 API 标识，允许修正录入错误而不改变资源地址。

### 3. REST 契约与查询

| 方法与路径 | 行为 | 成功响应 |
|---|---|---|
| `POST /api/servers` | 创建 | 201，完整资产 |
| `GET /api/servers` | 分页查询 | 200，`items,total,page,page_size` |
| `GET /api/servers/{id}` | 详情 | 200，完整资产 |
| `PATCH /api/servers/{id}` | 部分更新 | 200，完整资产 |
| `DELETE /api/servers/{id}` | 永久删除 | 204 |

PATCH 的缺省字段保持原值，可选字段传 null 表示清空，必填字段或状态传 null 返回 422；ID、创建和更新时间只读。创建或更新必须在同一数据库事务完成。数据库唯一冲突转换为 409；不存在资源返回 404；参数或字段错误返回 422；无效 UUID 返回 422。错误采用统一 JSON 结构 `code,message,field_errors`，其中消息为英文，前端不得显示数据库原始异常。

查询参数为 `q,model,status,page,page_size`；多个关键词目标字段采用 OR，各筛选项之间采用 AND；搜索中的 `%`、`_` 作为普通字符处理。采用 LIMIT/OFFSET，按 `created_at DESC,id DESC` 排序，过滤条件同时用于 count。首版数据量不预设大规模，先使用参数化查询和唯一索引，不引入搜索服务。并发编辑采用最后提交覆盖，暂不实现版本锁。

### 4. 页面及语言

提供 `/servers` 列表、`/servers/new` 添加页、`/servers/:id` 详情页和 `/servers/:id/edit` 编辑页。列表展示名称、Service Tag、型号、管理 IP、位置、负责人、状态与操作；详细配置放在详情。搜索或筛选变更时回到第一页。

UI 文案集中维护英文常量，无需首版引入语言切换框架。状态值映射为 `Available`、`In Use`、`Under Maintenance`、`Retired`。表单含必填和格式提示；保存时禁用重复提交；失败保留输入。删除确认展示名称、Service Tag 和永久删除含义，默认焦点置于取消按钮。提供加载、空状态、找不到资产和失败重试。中文资产内容正常保存与展示。

### 5. kind 部署、迁移与持久化

使用独立命名空间 `cap`，前端和 API 使用 Deployment 与 ClusterIP Service，PostgreSQL 使用单副本 StatefulSet、内部 Service 和 PVC。采用可替换镜像 tag，并向指定 kind 集群加载镜像，应用镜像使用 `IfNotPresent`；不修改用户 kubeconfig 默认上下文。命令显式传入上下文，部署前检查连接及可用 StorageClass。若没有动态供给能力，文档要求先配置适用的存储，不静默使用临时目录。

配置通过 ConfigMap 与 Secret 注入，仓库只存占位模板，运行时生成本地数据库凭据。使用集群内 DNS 连接数据库。本地访问采用 `kubectl --context <context> -n cap port-forward --address 127.0.0.1 svc/frontend 8080:80`，不暴露数据库、不要求 Ingress。

迁移使用独立 Job，显式等待完成后启动或更新 API；不在每个 API 副本启动时自动迁移。API `/health/live` 检查进程，`/health/ready` 检查数据库连通与 schema revision；部署配置相应探针。PostgreSQL 使用就绪探针，前端使用 HTTP 探针。文档给出检查 Pod、Job 和日志的命令。

PVC 可跨 Pod 重建保留数据，但不承诺跨 PVC 删除或 kind 集群重建保留。文档提供 pg_dump 导出到宿主机及恢复步骤；默认卸载逐项删除工作负载，保留 PVC 和命名空间，避免 namespace 删除误删数据。

### 6. 未决需求的首版默认值

为使提案可实施，采用配置摘要、永久删除、无登录和无审计；这些是提案选择，尚未获得用户逐项确认。无登录的部署只面向本机，不作为多人或公网环境方案。用户以后要求登录、恢复删除或硬件明细时，应同步修订规格、设计与任务。

## Risks / Trade-offs

- [永久删除不可恢复] → 明确英文确认，退役保留记录；提供数据库备份步骤。
- [无登录意味着应用不识别操作者] → 本机回环访问，文档明确使用边界。
- [kind 数据依赖节点容器与卷生命周期] → 使用 PVC，并在销毁集群前导出集群外备份。
- [唯一性并发冲突] → 数据库 UNIQUE 兜底，转换为可读 409。
- [摘要字段不便做精细硬件统计] → 首版优先完成台账，未来按新需求扩展模型。
- [集群存储和镜像来源尚未实测] → 实施时先检查现有上下文和存储，使用明确版本、镜像加载和拉取策略。

## Migration Plan

1. 实施时检查用户现有 kind 集群、上下文和存储，构建镜像并加载到目标集群。
2. 创建命名空间、配置、Secret、数据库与 PVC，等待数据库就绪。
3. 执行初始迁移 Job 并确认成功，再部署 API 与前端。
4. 使用本机入口验证增删改查、英文文案和中文数据；重建数据库 Pod 验证数据保留；验证备份与恢复。
5. 更新 README 和部署文档，记录准确的构建、部署、迁移、访问、备份和卸载命令。

首次部署没有存量业务 schema。迁移失败时停止应用发布、检查 Job，不自动删除数据库。应用回滚使用前一镜像；涉及 schema 回退时先备份并检查迁移兼容性，禁止默认执行破坏性回退。卸载工作负载保留 PVC；删除 PVC 或集群是单独且明确的数据销毁操作。
