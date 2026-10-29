## Why

项目已有 Python/React 应用、Dockerfile 和 Helm Chart，但缺少统一的 PR 质量检查及 GHCR 制品发布流程。先建立可追溯的镜像和 Chart 发布基础，后续 change 再接入 Flux 部署、集群内测试及测试环境生命周期管理。

## What Changes

- PR 创建、更新或重新打开时，提供六条独立且名称稳定的 Check：`Static Checks`、`Code Tests`、`Build and Publish Images`、`Helm Validation`、`Package and Publish Chart`、`Chart Version Check`。
- PR 存在代码、测试、构建或 Chart 相关改动时，要求 `charts/cap/Chart.yaml` 的 version 按 SemVer 严格高于目标分支版本；纯文档或 OpenSpec 规划改动不强制 bump。
- 增加 Python Ruff、前端 ESLint 与 TypeScript 类型检查入口。使用隔离的临时 PostgreSQL 运行现有后端集成测试；另外运行现有发布预检查逻辑的单元测试，后者使用 mock，不连接数据库或 Kubernetes 集群，也不执行实际部署。
- 校验默认、kind、legacy values 的 Helm lint/template 行为，并运行现有 Chart 测试；这些检查不连接 Kubernetes 集群。
- 在质量检查通过后构建前后端 Docker 镜像并推送 GHCR，再将绑定同次构建镜像的 Helm Chart 打包并推送 GHCR OCI Registry。
- main 分支发生 push（包括 PR 合并）后，检查同一提交并自动发布前后端镜像和 Chart。
- PR 镜像 tag 使用完整 head commit SHA，Chart 发布版本由源码 Chart version 加 `-sha<完整 SHA>` 组成；main 使用相同规则，但 SHA 来自 PR 合并后 main 的准确提交。版本不附加 PR 编号、run ID 或 attempt；同 SHA 重跑复用已验证的制品并补齐缺失项，不覆盖已有版本。
- 记录源提交 SHA、运行编号、镜像引用与 digest、Chart 版本与 OCI digest，为后续部署提供准确的制品入口。
- 以维护者已在仓库层限制 collaborators-only 提交 PR 为信任边界，所有进入流水线的 PR 统一执行六项检查和制品发布，不增加 Fork PR 的专门分流逻辑。
- 本 change 不包含部署、Flux/GitOps 配置、E2E、测试报告平台、手动测试环境清理、云资源或集群认证，也不创建第二个 change。

## Capabilities

### New Capabilities

- `ci-artifact-publishing`: 定义 PR 六项检查、代码改动的 Chart 版本提升门禁、隔离测试、GHCR 镜像与 Chart 发布、main 自动发布、版本追溯及发布权限边界。

### Modified Capabilities

无。现有资产 API、Helm 安装/卸载与数据保留、本地 kind 部署行为不变。

## Impact

- 新增 `.github/workflows/` 中的 PR/main 自动化及可复用检查、发布逻辑。
- 更新 Python/前端开发依赖、锁文件、静态检查配置和必要的现有代码问题；不改变业务行为，不将本次扩展为全仓格式重写。
- 增加制品元数据生成、Chart 暂存打包及验证入口；复用现有 Dockerfile、Chart 和测试。
- 增加中文 CI/GHCR 使用文档，修订 `docs/prepare.md`，区分本 change 的准备项与后续部署准备项。
- 使用 GitHub 标准 Linux Runner 和作业内临时 PostgreSQL；发布使用最小权限 `GITHUB_TOKEN`，无需阿里云、Kubernetes 或长期 PAT 凭据。
