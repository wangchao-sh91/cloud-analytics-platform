## Why

当前部署依赖 shell 脚本直接应用 Kubernetes 清单，配置分散，安装、升级和资源生命周期缺少统一入口。将已验证的 kind 部署转为 Helm Chart，使前端、API、PostgreSQL 和迁移任务通过一个 release 管理，并保留现有资产数据和凭据。

## What Changes

- 新增 `charts/cap/`，包含前端、API、单副本 PostgreSQL、数据库迁移 Job、Service、ConfigMap、Secret 和持久化配置。
- 使用 values 管理镜像、资源配额、副本数、存储类和容量，提供 kind 环境配置；数据库始终随 Chart 部署，本次不支持外部 PostgreSQL。
- 将镜像构建与 kind 加载从部署生命周期中拆出；Helm 成为安装、升级、卸载和重新安装的统一入口。
- 为首次安装和升级设计数据库等待、独立迁移及 API 启动等待，避免迁移与就绪检查形成循环等待。
- 提供现有 `cap-001` 部署的明确接管流程，复用现有 PostgreSQL、PVC 与 Secret；升级保持凭据稳定，卸载保留数据和凭据，并验证同 release 重新安装可用。
- **BREAKING**：停止以 `infra/k8s/` 清单及原有直接 apply 逻辑作为受支持的发布入口，文档迁移至 Helm；既有部署需要先执行接管流程，不直接重复安装覆盖资源。
- 保持英文 UI、中文文档、本机回环访问和既有资产 API 行为。

## Capabilities

### New Capabilities

- `helm-chart-deployment`: Chart 配置、安装升级、迁移等待、资源命名隔离、现有部署接管、凭据稳定及卸载后重新安装的数据保留契约。

### Modified Capabilities

无。当前主规格目录尚无规格，`cap-001` 已实施完成但尚未归档；本变更新增 Helm 发布能力，不修改其历史规划文件，也不改变资产管理契约。Chart 模板继续提供原部署规格要求的 Kubernetes 资源与本地访问能力。

## Impact

- 涉及 `charts/cap/`、镜像准备和部署脚本、原始清单、前端 Nginx 配置注入、后端启动等待工具及开发运维文档。
- 实施需准备 Helm CLI，并锁定、记录实际验证版本；继续使用现有 kind 集群，支持在隔离命名空间验证完整生命周期。
- 接管前执行集群外备份及资源一致性检查；不删除原 PVC、不重新生成现有凭据、不自动重建数据库或修改数据库大版本。
- 本轮仅生成提案、规格、设计和任务，不安装工具、不修改应用或集群资源，也不自动归档 `cap-001`。
