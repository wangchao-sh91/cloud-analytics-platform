# CI 发布准备清单

当前 cap-003 的范围是 PR 六项检查及 main 自动发布镜像、Helm Chart 到 GHCR。部署、Flux、集群内 E2E、GitHub Checks 回报和手动环境清理在后续 change 实现。

## 本次必须准备

1. 使用现有 GitHub 仓库 `wangchao-sh91/cloud-analytics-platform`，维护者已在仓库层限制 collaborators-only 提交 PR。
2. 仓库 Settings → Actions → General，允许 GitHub Actions 及 Workflow 使用的官方 Actions。使用标准 Linux Runner；本次不需要购买或注册 Runner ECS。
3. 保持默认 token 权限为只读即可。Workflow 仅在镜像和 Chart 发布 Job 声明 `packages: write`；若组织策略限制 Package 写入，需由管理员允许。`GITHUB_TOKEN` 由 GitHub 自动提供，不手动创建 PAT 或保存云端密钥。
4. 对本次代码改动，将 `charts/cap/Chart.yaml` version 提升到高于 PR base 的稳定版本。本 change 已提升为 `0.3.0`；若目标 main 后续采用相同或更高版本，合并前需再次提升。
5. 提交 PR，查看 Static Checks、Code Tests、Helm Validation、Chart Version Check、Build and Publish Images、Package and Publish Chart 六项结果。发布逻辑和版本规则见 [CI 文档](ci-and-publishing.md)。

## 首次发布后的 GHCR 设置

无需提前创建 GHCR namespace 或 Package。owner 即 `wangchao-sh91`，首次推送自动创建：

```text
ghcr.io/wangchao-sh91/cap-backend
ghcr.io/wangchao-sh91/cap-frontend
oci://ghcr.io/wangchao-sh91/charts/cap
```

1. 个人主页 → Packages，查看各 Package 是否关联当前源码仓库。
2. 对于之前手动创建、未继承本仓库权限的 Package，Package settings → Manage Actions access，给当前仓库写权限。
3. 按需要决定 Public 或 Private；本次 Workflow 不改变可见性。Private 读取需要相应权限，后续 Flux 拉取身份另行设计。
4. 从成功运行下载 release artifact，按其中的镜像 digest 和 Chart version 读取并核对制品。Package 推送成功不等于已经部署应用。
5. 首次完整运行后，在 Settings → Rules → Rulesets 或分支保护中，将六条检查设为 main 合并的 required checks。

## 本地验证需要

- Python 3.12、uv、Node.js 22.13+ 的 22.x 版本。
- 临时 PostgreSQL 17（可通过项目脚本自动使用本机 Docker 创建和清理）。
- Helm v3.19.0、actionlint v1.7.12，可用项目安装脚本安装到 `.tools/`。
- 无需 Kubernetes 集群；命令见[开发文档](development-and-deployment.md)。

## 后续部署准备

ACK、VPC/交换机、公网出口、存储类、Flux bootstrap、GitOps 仓库、集群内测试与结果回报身份等准备，属于后续 change，不是 cap-003 的执行前置条件。现有云资源可以保留用于后续学习，但本次 Workflow 不会使用或修改它们，也不会创建或清理任何测试 Namespace。
