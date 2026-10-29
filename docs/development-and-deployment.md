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

## 本地代码质量检查

需要 Python 3.12、uv 和 Node.js 22.13 或更高的 22.x 版本（ESLint 10 的运行要求）。首次运行或依赖变化后，在仓库根目录安装锁定的开发依赖：

```bash
uv sync --project apps/backend --frozen
npm --prefix apps/frontend ci
```

在仓库根目录统一运行 Python 静态检查、前端 ESLint 和 TypeScript 类型检查：

```bash
bash scripts/check-quality.sh
```

也可以分别执行：

```bash
uv run --project apps/backend --frozen ruff check apps/backend scripts
npm --prefix apps/frontend run lint
npm --prefix apps/frontend run typecheck
```

Ruff 使用根目录 `ruff.toml` 的 E4/E7/E9/F 正确性规则，覆盖后端源码、迁移、测试及 Python 发布脚本和测试。ESLint 覆盖前端源码、测试和配置，并检查 React Hooks 使用及依赖；依赖、构建产物和测试报告目录不参与检查。任一检查失败都会返回非零状态；这些静态检查不需要数据库、运行中的应用或 Kubernetes 集群。

`npm run build` 和 `npm test` 保持原有用途，分别执行生产构建和 Playwright 浏览器测试。

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

以下入口均在仓库根目录执行，先按“本地代码质量检查”安装锁定的开发依赖。mock 单元测试不需要数据库、运行中的应用或集群：

```bash
uv run --project apps/backend --frozen python scripts/check_code.py unit
```

该入口运行后端启动等待逻辑、发布预检查逻辑和 CI 检查工具的单元测试，清除子进程中的数据库连接变量；Chart 测试由独立 Helm 入口执行。

后端集成测试会迁移并清空测试库资产表，必须使用独立的一次性 PostgreSQL 17，不能指向正常台账库。推荐通过 Docker 自动创建并清理临时库：

```bash
bash scripts/test-postgres.sh
```

脚本使用随机密码、动态回环端口和内存临时数据目录，不挂载已有卷，不读取 `.env` 或既有业务库配置；单元测试和后端测试结束后（包括测试失败）仅删除本次容器及其临时数据。需要可用的本机 Docker；首次运行可能下载 `postgres:17` 镜像。

CI service 或已有专用测试库也可以显式提供连接，避免再启动 Docker。连接格式为 `postgresql+psycopg://<user>:<password>@<host>:<port>/<test_db>`，密码特殊字符需百分号编码；用交互方式输入，避免凭据进入命令历史：

```bash
read -rsp 'Disposable test database URL: ' TEST_DATABASE_URL
echo
export TEST_DATABASE_URL
uv run --project apps/backend --frozen python scripts/check_code.py backend
unset TEST_DATABASE_URL
```

后端入口等待数据库就绪（默认 30 秒，可用 `--db-timeout` 调整），确认 PostgreSQL 主版本为 17，然后执行完整后端 pytest；测试 fixture 执行迁移。没有 `TEST_DATABASE_URL`、等待超时、迁移或断言失败均返回非零状态，不回退使用 `DATABASE_URL`，不跳过集成测试。`all` 模式依次运行单元和后端测试，也必须显式提供测试库。

### 无集群 Helm 校验

```bash
bash scripts/install-helm.sh
bash scripts/check-helm.sh
```

校验入口固定 Helm v3.19.0 和渲染目标 Kubernetes 1.35.8；默认使用 `.tools/helm-v3.19.0`，也可以通过绝对路径 `HELM` 指定同版本可执行文件。依次校验默认、kind、legacy values 的 lint/template，并运行现有 Chart pytest；设置空 kubeconfig，不安装或修改集群资源。渲染结果可能含临时生成的 Secret，入口不打印 YAML。这只验证模板，不代表部署或运行时验收已通过。

### Chart 版本提升检查

PR 的代码、测试、依赖、构建脚本、CI 或 Chart 改动要求将 `charts/cap/Chart.yaml` 的 `version` 提升到严格高于本次 PR base 的版本。源码版本使用稳定 `MAJOR.MINOR.PATCH`，例如 `0.2.9` 到 `0.2.10`；修改 appVersion 或 CI 添加提交后缀不算 bump。同一 PR 后续提交无需逐次 bump，只需保持高于当前比较基准。

```bash
# PR_BASE_SHA / PR_HEAD_SHA 必须是准确的完整提交 SHA，且本地拥有完整 Git 历史。
uv run --project apps/backend --frozen python scripts/check_chart_version.py \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"

# main 发布只校验该提交的源码版本格式，不重新执行 PR bump 比较。
uv run --project apps/backend --frozen python scripts/check_chart_version.py \
  --event push --head "$(git rev-parse HEAD)"
```

净改动来自 base/head 的 merge-base 到 head，版本大小比较读取准确 base SHA 与 head SHA。`docs/**`、`openspec/**`、根目录 `.md` 和 `LICENSE`/`LICENSE.*` 为纯文档豁免；其他文件保守地按代码处理，删除及跨目录重命名也会检查。仅文档时明确通过并说明无需 bump；缺少提交/完整历史、版本格式无效或版本未提升时明确失败。该入口只读 Git 对象，不修改源码版本或工作区。

### 浏览器测试

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
