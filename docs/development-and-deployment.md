# 开发与本地 kind 部署

## 本地开发

准备专用 PostgreSQL 17 数据库，使用自己的密码配置连接，不要把实际凭据提交到仓库。可启动独立开发库（交互输入密码，避免出现在命令历史中）：

```bash
read -rsp 'Database password: ' POSTGRES_PASSWORD
echo
export POSTGRES_PASSWORD
docker run -d --name cap-dev-postgres -e POSTGRES_PASSWORD -e POSTGRES_USER=cap -e POSTGRES_DB=cap -p 127.0.0.1:55432:5432 postgres:17
unset POSTGRES_PASSWORD
```

后端需要 Python 3.12 与 uv，在 `apps/backend/` 执行：

```bash
uv sync --locked
cp .env.example .env
# 编辑 .env，填入自己的 DATABASE_URL；URL 中特殊字符需要百分号编码。
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端需要 Node.js 22，在 `apps/frontend/` 执行：

```bash
npm ci
npm run dev
```

访问 http://127.0.0.1:5173 ，Vite 将 `/api` 转发到本机 8000。API 文档在 http://127.0.0.1:8000/docs 。不要同时使用占用相同端口的其他程序。

## 数据与接口

必填字段为 `name`、`service_tag`、`model`；状态默认 `available`。支持 `available`、`in_use`、`maintenance`、`retired`。Service Tag 自动去首尾空白并转大写，重复返回 409。管理 IP 与 iDRAC IP 支持 IPv4/IPv6；它们仅作为台账文本保存，不产生设备连接。

资产资源路径为 `/api/servers`，提供 POST、GET 列表，以及 `/{id}` 的 GET、PATCH、DELETE。列表参数为 `q,model,status,page,page_size`，返回 `items,total,page,page_size`。分页默认 1/20，page_size 最大 100。PATCH 缺省字段不变，可选字段传 null 清空，必填字段和状态不允许 null。删除成功返回 204，不存在返回 404，校验失败返回 422。

英文错误格式为 `{"code":"validation_error","message":"Please check the highlighted fields.","field_errors":{"name":"..."}}`。用户内容允许中文；UI 标题、表单、按钮和反馈均为英文。

## Helm 集群部署

使用 Helm v3.19.0、Kubernetes ≥1.32，数据库固定 PostgreSQL 17 单副本。先检查目标与存储：

```bash
kind get clusters
kubectl --context kind-kind get nodes
kubectl --context kind-kind get storageclass
bash scripts/install-helm.sh
export HELM="$PWD/.tools/helm-v3.19.0"
```

工具安装脚本从 Helm 官方下载并校验 SHA-256，写入被 Git 排除的 `.tools/`，不需要系统目录权限。已有受验证 Helm 时可直接设置 `HELM` 为其路径。

镜像准备与应用发布是两个步骤：

```bash
bash scripts/prepare-images.sh kind kind-kind cap002-v1
bash scripts/deploy.sh --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml
```

准备脚本检查 kind 集群名和上下文对应关系，构建并加载应用镜像；发布脚本先做只读预检，再调用 Helm upgrade --install，等待工作负载与迁移 Job 完成。Chart 内同时部署 PostgreSQL，不支持外部数据库。命名空间不存在时由 Helm 创建，Chart 本身不管理 namespace 对象。

默认镜像 tag 为 cap002-v1。代码变更时使用新 tag，并给发布命令追加 `--set backend.image.tag=<tag> --set frontend.image.tag=<tag>`。每次升级都会生成新 revision 的迁移 Job，即使 tag 相同也不会复用旧任务结果。数据库等待、迁移和 API 初始化都有超时；失败不会自动删库或降级 schema，修复后执行新的 upgrade。

默认资源名以 `<release>-cap-` 开头；可以通过 Helm NOTES 获取准确服务名。全新部署示例：

```bash
kubectl --context kind-kind -n cap get pods,svc,pvc,jobs
kubectl --context kind-kind -n cap port-forward --address 127.0.0.1 svc/cap-cap-frontend 8080:80
```

访问 http://127.0.0.1:8080 。Nginx 配置由 Chart 注入，代理同一 release 的 API。默认服务为 ClusterIP，不暴露数据库；无登录的应用仅用于本地访问。已接管的 cap-001 使用 legacy 模式，前端 Service 为 `frontend`，后端为 `api`，数据库为 `postgres`。后续升级始终同时传入 kind 与 legacy values。

已有 cap-001 资源必须先按[运维文档](operations.md)备份并显式接管。`infra/legacy-k8s/` 只保存迁移比对资料，不再作为独立发布入口；不要将旧清单与 Helm 混用。

直接使用 Helm 时，也应先运行只读预检：

```bash
python3 scripts/release.py check --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml
"$HELM" upgrade --install cap charts/cap --kube-context kind-kind -n cap --create-namespace -f charts/cap/values-kind.yaml --wait --wait-for-jobs --timeout 10m
```

静态检查不连接 live Secret，不能判断现有卷与凭据的匹配关系：

```bash
"$HELM" lint charts/cap -f charts/cap/values-kind.yaml
# 渲染输出可能含生成的 Secret，请勿提交到仓库或公开日志。
"$HELM" template review charts/cap -f charts/cap/values-kind.yaml > /tmp/cap-review.yaml
HELM="$HELM" apps/backend/.venv/bin/pytest -q scripts/tests apps/backend/tests/test_wait.py
```

## 测试

后端集成测试会清空测试库资产表，必须使用独立测试数据库，不能指向正常台账库。在 `apps/backend/` 设置 `TEST_DATABASE_URL` 为专用库连接后执行：

```bash
uv run pytest -q
```

在 `apps/frontend/` 执行类型检查、构建及浏览器测试：

```bash
npm run build
npx playwright install chromium --no-shell
npm test
```

若浏览器提示缺少系统动态库，在具备系统安装权限的终端运行 `npx playwright install-deps chromium` 后重试；这些依赖只用于浏览器测试，不影响生产静态资源。

浏览器测试默认访问已启动的开发页面 5173，后端须运行；也可通过 `BASE_URL=http://127.0.0.1:8080 npm test` 验证部署入口。测试创建唯一 Service Tag 的资产，完成流程后删除；中途失败可能残留记录，核对后清理。

## 故障排查

- `Pending`：检查 `kubectl --context kind-kind -n cap describe pvc data-cap-cap-postgres-0` 和存储类。
- `ImagePullBackOff`：检查仓库连通性、镜像 tag、kind load 执行结果和节点内镜像。
- 迁移失败：查看 Job 日志，停止发布；不要删除 PVC 或用删库重建替代修复。
- API 未就绪：查看 `kubectl --context kind-kind -n cap logs deployment/cap-cap-api -c api`，核对 Secret、数据库和迁移 Job。
- 页面无法访问：确认 port-forward 仍在运行、本机端口未冲突；API 失败检查前后端日志。
- 依赖或基础镜像下载失败：检查本机网络或已有代理配置，恢复连接后用新 tag 重试部署。

诊断命令使用默认命名示例；legacy 模式使用原资源名。检查迁移 Job 日志及 API 初始化容器：`kubectl --context kind-kind -n cap logs job/<当前迁移Job> -c migrate`、`kubectl --context kind-kind -n cap logs deployment/<API名称> -c wait-migration`。不要手动删除当前 revision 的成功 Job，API Pod 重建需要查询它的完成状态。
