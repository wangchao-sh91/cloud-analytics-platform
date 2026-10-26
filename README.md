# Lab Dell PowerEdge 物理机管理平台

用于人工维护 Lab 物理机资产，支持新增、编辑、永久删除、列表、详情、分页、搜索及型号和使用状态筛选。文档使用中文，用户界面及错误提示使用英文，录入内容支持中文。

- 后端：Python 3.12、FastAPI、SQLAlchemy、Alembic。
- 数据库：PostgreSQL 17。
- 前端：React、TypeScript、Vite，生产环境由 Nginx 提供页面与 API 同源入口。
- 部署：Helm Chart 统一管理前端、API 与 PostgreSQL；本地使用现有 kind 集群，数据库使用 PVC。

首版只维护台账，不连接 iDRAC、不采集设备数据、不执行开关机、不存储设备凭据。硬件配置使用摘要字段。无登录和角色权限，仅用于本机访问；删除不可在 UI 中恢复，退出使用的设备可设置为 `Retired`。

全新部署：

```bash
bash scripts/install-helm.sh
export HELM="$PWD/.tools/helm-v3.19.0"
bash scripts/prepare-images.sh kind kind-kind cap002-v1
bash scripts/deploy.sh --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml
kubectl --context kind-kind -n cap port-forward --address 127.0.0.1 svc/cap-cap-frontend 8080:80
```

浏览器访问 http://127.0.0.1:8080 。已存在的 cap-001 部署先执行[显式接管流程](docs/operations.md)，不能直接运行全新部署命令。接管后使用 legacy 资源名，前端 Service 仍为 `frontend`。

验证工具为 Helm v3.19.0、Kubernetes v1.35.8，Chart 要求 Kubernetes ≥1.32。还需 Docker、kind、kubectl 和 Python 3。Chart 默认卸载保留数据库 PVC 和凭据；同 release、namespace、命名模式和数据库配置重新安装可复用原数据。

详见 [Chart 使用说明](charts/cap/README.md)、[开发与部署](docs/development-and-deployment.md)、[备份与运维](docs/operations.md)、[Helm 验证记录](docs/helm-verification.md)。

资产台账规划见 [cap-001](openspec/changes/archive/2026-10-26-cap-001/proposal.md)，Helm 发布规划见 [cap-002](openspec/changes/archive/2026-10-26-cap-002/proposal.md)。
