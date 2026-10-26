# cap-001 验证记录

首轮验证日期：2026-10-20；集群复验日期：2026-10-23。任务 5.5、5.6 已通过实际集群验证，当前完成 26/26 项任务。

## 已通过

- 现有集群检查：`kind` 集群，`kind-kind` context，节点 Ready，默认 `standard` StorageClass 可用。
- Python 依赖锁定与安装：`uv lock --project apps/backend`、`uv sync --project apps/backend --locked`。
- PostgreSQL 17 集成测试：独立 `cap-test-postgres` 容器映射本机 55432，在 `apps/backend` 执行 `TEST_DATABASE_URL=postgresql+psycopg://cap@127.0.0.1:55432/cap .venv/bin/pytest -q`，17 项通过。
- 测试覆盖：初始迁移、重复 upgrade、唯一性数据库约束、CRUD、中文数据、Service Tag 规范化、创建及编辑冲突、必填项、IP、状态、U 位、字段长度、只读字段、PATCH 清空、搜索通配字符、组合筛选、分页、找不到资源和迁移版本未匹配的就绪检查。
- 前端依赖安装：`npm install --registry=https://registry.npmjs.org --fetch-retries=1 --fetch-timeout=30000`，生成 package-lock.json。
- 前端类型检查及生产构建：`npm run build` 通过。
- 英文 UI 静态检查：`rg -n '[\p{Han}]' apps/frontend/src apps/frontend/index.html` 无匹配；中文只存在于测试数据和项目文档中。
- Kubernetes 清单 dry-run：namespace、database 及替换 IMAGE_TAG 后的 application、migration 清单通过 `kubectl --context kind-kind apply --dry-run=client`，未创建实际资源。
- `bash -n scripts/deploy.sh` 通过。
- `openspec validate cap-001 --strict` 通过。

## 浏览器验证

3 个 Playwright 测试全部通过：英文 UI 与中文数据完整操作流程、表单失败保留输入、列表失败重试。完整流程覆盖添加、编辑、状态修改、组合搜索筛选、详情、取消删除、确认删除和删除后 404。

Chromium 已下载；环境缺少 `libasound.so.2`，系统安装需要交互式 sudo，因此使用下载到 `/tmp/cap-browser-libs` 的 Ubuntu 运行库验证，不修改系统目录。最终命令为在前端目录执行 `LD_LIBRARY_PATH=/tmp/cap-browser-libs/usr/lib/x86_64-linux-gnu npm test`，结果 3 passed。可在准备好系统浏览器依赖的环境直接运行 `npm test`。

浏览器验证发现并修正状态选择框和添加按钮图标的可访问名称。桌面 1440px 与手机 390px 截图已检查，表格在窄屏内横向滚动。前端最终 `npm run build` 通过。首轮完成 24/26 项任务，当时剩余 5.5、5.6，现已完成，见下方集群复验记录。

## 首轮集群验证阻塞（2026-10-20）

Docker Hub 的 python:3.12-slim、node:22-alpine、nginx:1.28-alpine 拉取出现 EOF/TLS handshake timeout；GHCR 的 uv 镜像和 Google 镜像缓存源也无法成功拉取。现有 PostgreSQL 测试镜像可用，后端测试未受影响。

当时未完成容器镜像构建、现有 kind 集群实际部署、8080 入口验证、数据库 Pod 重建及集群外备份恢复验证，也未创建 cap 命名空间。本次复验已解除上述阻塞。

## kind 部署及同源 CRUD 复验（任务 5.5，2026-10-23）

网络仍偶发 EOF，但重试后前后端基础镜像及依赖均成功下载，使用以下命令完成实际部署，未重新创建或删除原有 kind 集群：

```bash
bash scripts/deploy.sh kind kind-kind cap001-20261023
kubectl --context kind-kind -n cap port-forward --address 127.0.0.1 svc/frontend 8080:80
```

- 应用镜像：`cap-backend:cap001-20261023`、`cap-frontend:cap001-20261023`，镜像构建和 kind 加载成功。
- 独立迁移 Job：`migrate-cap001-20261023`，Complete 1/1。
- `api`、`frontend` Deployment 和 `postgres` StatefulSet 均就绪；`data-postgres-0` PVC 为 Bound，容量 2Gi，使用 standard 存储类。
- API、前端、数据库 Service 均为 ClusterIP；8080 入口仅绑定 `127.0.0.1`，由前端 Nginx 同源转发 `/api`。
- API `/health/ready` 返回 `{"status":"ready"}`。
- 在 `apps/frontend/` 执行 `BASE_URL=http://127.0.0.1:8080 LD_LIBRARY_PATH=/tmp/cap-browser-libs/usr/lib/x86_64-linux-gnu npm test`，3 passed。完整 CRUD 使用真实的集群 API 与 PostgreSQL；另外两项验证请求失败和重试。

复验时本地 PostgreSQL 多平台镜像缓存直接通过 `kind load docker-image` 导入出现 missing content digest。以 `docker image save --platform linux/amd64 -o /tmp/cap-postgres17-amd64.tar postgres:17` 导出本机平台，再执行 `kind load image-archive --name kind /tmp/cap-postgres17-amd64.tar` 后成功加载。该处理没有修改数据库镜像或集群配置；应用镜像正常使用部署脚本加载。

## Pod 重建及备份恢复复验（任务 5.6，2026-10-23）

通过 8080 入口创建专用资产 `PERSIST20261023024137`，包含中文名称、负责人、备注、IPv4/IPv6、位置、硬件摘要和状态。记录内部 ID 为 `dcadac10-1807-4827-a167-0f52cbd922d1`。

1. 使用 `pg_dump -U cap -d cap -Fc` 将集群数据库导出至宿主机 `backups/cap-20261023024137.dump`，4387 字节，SHA-256 为 `b42d7ded86664b9b4716723b1283e743cab362b5e724ccac1906c282693e7973`。
2. 删除并重建 `postgres-0`，等待新 Pod Ready。旧 UID 为 `f946ba28-7358-479c-897e-cd38ef20b222`，新 UID 为 `f9f83687-9590-4373-85c9-2aa9e3bc75ac`；PVC UID 始终为 `07705399-bc32-4f3a-a601-f118dc83b11e`。
3. 通过同源 API 重新读取资产，确认 ID、创建和更新时间及全部字段与重建前完全相同；数据库整表查询结果也一致。
4. 创建独立空库 `cap_restore_20261023024137`，从宿主机备份通过标准输入执行 `pg_restore --no-owner --no-privileges --exit-on-error`。
5. 逐字段比较源库与恢复库资产整表 JSON：源库 1 条，恢复库 1 条，全部一致；恢复库迁移版本为 `001_inventory`，资产原有 ID 和中文内容保持不变。
6. 验证完成后仅删除专用测试资产与临时恢复库，保留集群应用、PVC 和宿主机备份。备份包含测试资产，已被 `.gitignore` 排除，不提交仓库。

验证证明 Pod 重建时复用 PVC 能保留数据，且本次集群外备份可恢复到独立空库；不代表 PVC 或 kind 集群删除后无需备份即可恢复。
