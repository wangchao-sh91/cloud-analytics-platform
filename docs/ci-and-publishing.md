# CI 检查与 GHCR 制品发布

cap-003 为目标 main 的 PR，以及 main 分支 push 提供六条检查。使用 GitHub 标准 Linux Runner，无需 ACK、Flux、自托管 Runner、云端凭据或 kubeconfig；不执行部署、浏览器 E2E 或环境清理。仓库已由维护者限制 collaborators-only 提交 PR，Workflow 不增加 Fork 专门分流。

## 六条检查

| Check | 内容 |
|---|---|
| Static Checks | Ruff、前端 ESLint 和 TypeScript 类型检查 |
| Code Tests | 无数据库凭据的 mock 单元测试、独立临时 PostgreSQL 17 上的后端测试 |
| Helm Validation | Helm v3.19.0，Kubernetes 1.35.8 离线目标，默认/kind/legacy values lint/template 和 Chart 回归测试 |
| Chart Version Check | PR 代码相关改动必须提升源码 Chart version；main 只校验版本格式 |
| Build and Publish Images | 前四项通过后构建或复用 linux/amd64 前后端镜像，推送 GHCR |
| Package and Publish Chart | 校验镜像、临时打包 Chart、推送 GHCR、读回验收并上传发布清单 |

PR opened/synchronize/reopened 均触发。没有路径过滤，纯文档 PR 仍产生全部检查。质量门禁失败时，下游发布 Job 明确失败，不用 skipped 掩盖前置失败。若推送部分成功后失败，残留制品不视为完整发布，不生成成功清单。

Code Tests 的 PostgreSQL service 只映射至 Runner 的回环地址，使用无密码 trust 认证；它是本次作业专用临时服务，不能作为长期数据库的配置示例。单元测试步骤不注入数据库连接变量，后端测试步骤显式连接该临时库；不加载部署环境 `.env`。

PR 检查和制品使用事件的完整 head SHA，不是 GitHub 默认的合并预览 SHA；这不表示已经测试与最新 main 的合并结果。main 使用 push 事件的实际提交 SHA，包括普通 merge、squash 或 rebase 后产生的最终提交。需要限制直接推送或要求 PR 跟上 main 时，在仓库 Rulesets 中配置。

## Chart 版本规则

源码 `charts/cap/Chart.yaml` 的 version 使用稳定 `MAJOR.MINOR.PATCH`。应用、依赖、测试、Dockerfile、脚本、Chart、CI 和其他构建配置的改动都需要 bump，按 SemVer 数值比较，必须严格高于事件 base SHA 中的版本。修改 appVersion 或 CI 添加 SHA 后缀不能替代 bump。

PR 净改动由 merge-base 到 head 判断，不把目标分支独有的改动算进 PR。删除、重命名也检查，重命名同时检查旧、新路径；无法读取基准或完整历史时失败。只有 `docs/**`、`openspec/**`、根目录 `.md`、`LICENSE`/`LICENSE.*` 豁免。同一 PR 已提升后，无需每个追加 commit 都再 bump；如果 main 已采用相同或更高版本，需要再次提升。

## 制品地址与版本

默认地址由仓库 owner 小写生成：

```text
ghcr.io/wangchao-sh91/cap-backend:<完整 SHA>
ghcr.io/wangchao-sh91/cap-frontend:<完整 SHA>
oci://ghcr.io/wangchao-sh91/charts/cap --version <源码 version>-sha<完整 SHA>
```

例如源码 version 为 `0.3.0`，PR head 为 A，merge 后 main 提交为 B，则 PR 使用镜像 tag A、Chart `0.3.0-shaA`，main 使用 tag B、Chart `0.3.0-shaB`；A/B 在实际制品中是完整 40 位十六进制 SHA。appVersion 为对应完整 SHA。PR 编号、run ID、attempt 不进入制品版本；不使用 latest 或可变分支 tag，也不按 hash 后缀的排序判断发布先后。

源码中的 Chart 和 kind/legacy values 不会被打包步骤改写。临时 Chart 副本设置发布 version/appVersion、前后端镜像和 OCI source/revision 注解，再 lint、渲染、打包。迁移和 API 初始化容器使用同次后端镜像，PostgreSQL 仍使用官方镜像。

## 同一 SHA 重跑

已有镜像先核对 source/revision 和 linux/amd64 架构；已有 Chart 按精确版本读回，核对 source/revision、version/appVersion、镜像配置、内容 digest 和实际渲染。匹配则复用原 digest，只发布缺失项，不覆盖原版本。

鉴权、网络错误不视为制品不存在；只有 manifest HTTP 404 允许首次发布。来源或配置不一致时失败。重跑不能更新相同 SHA 的基础镜像或依赖解析结果，如需重新构建已有版本，需要提交新 commit。

同一 SHA 的镜像发布和 Chart 发布分别使用串行锁。不同 SHA 没有浮动 tag 竞争，可并行发布；PR 更新会取消旧 PR 运行，main 发布不主动取消其他 main 提交。

## 发布清单

成功后在 Actions Summary 查看精确引用与 digest，并下载 `release-<SHA>-<run_id>-<attempt>` artifact 中的 `release.json`，保留 7 天。字段包括：

| 字段 | 内容 |
|---|---|
| schema_version / status | `1` / `published` |
| repository / event / channel / pr | 来源仓库、事件、pr/main 渠道、PR 编号或 null |
| source_sha | 完整源提交 SHA |
| run_id / run_attempt / run_url | 运行追溯信息 |
| base_chart_version | 源码 Chart version |
| images.backend / images.frontend | repository、tag、digest |
| chart_repository / chart_version / chart_digest | Chart OCI 地址、精确版本和 manifest digest |

清单不含凭据，仅在两项镜像和 Chart 均完成验收后生成。Artifact 过期不删除 GHCR 制品；后续部署应保存精确引用/digest。源码及包的版本元数据不自动形成 GitHub Release 或 GitOps 配置提交。

按清单读取制品的示例（先填入本次实际值）：

```bash
docker pull "ghcr.io/wangchao-sh91/cap-backend@$BACKEND_DIGEST"
docker pull "ghcr.io/wangchao-sh91/cap-frontend@$FRONTEND_DIGEST"
helm pull oci://ghcr.io/wangchao-sh91/charts/cap --version "$CHART_VERSION"
```

Private Package 需要读取权限，Public Package 可匿名读取。Workflow 内发布和读回使用自动签发的 `GITHUB_TOKEN`；本地读取 Private 制品的凭据单独配置，不将其提交到仓库。

## 本地复现

依赖安装、隔离数据库和版本检查命令详见[开发文档](development-and-deployment.md)。在仓库根目录：

```bash
uv sync --project apps/backend --frozen
npm --prefix apps/frontend ci
bash scripts/check-quality.sh
uv run --project apps/backend --frozen python scripts/check_code.py unit
bash scripts/test-postgres.sh
bash scripts/install-helm.sh
bash scripts/check-helm.sh
bash scripts/install-actionlint.sh
.tools/actionlint-v1.7.12 -shellcheck= -pyflakes= .github/workflows/ci.yaml
```

actionlint 安装脚本下载官方固定版本并校验 SHA-256；在本地用它校验 Workflow 语法和 GitHub 表达式。此处禁用可选 shellcheck/pyflakes 集成，不影响 actionlint 自身检查；Python 静态检查由 Ruff 执行。

发布逻辑在 `scripts/ci_release.py`。`metadata` 从 GitHub 事件解析身份并确认当前 checkout，`images` 发布镜像，`chart` 发布/验收 Chart，`package` 可对现有元数据进行纯本地临时打包。不要将含未提交变更的工作区标记为某个已提交 SHA 发布；本地 Docker 构建验证也不能当作 GHCR 推送验收。

## 权限与故障排查

- Workflow 默认只有 `contents: read`，仅两个发布 Job 添加 `packages: write`。不需要 PAT、`contents: write` 或云平台 Secret。
- 首次推送自动创建 GHCR Package，不需要手动创建 namespace 或仓库。Package 可见性不会随源码仓库自动公开，Workflow 也不自动修改它。
- HTTP 401/403：确认仓库 Actions 策略允许 Package 写权限；对已有 Package，在 Package settings 的 Manage Actions access 给本仓库写权限。collaborators-only 限制不会改变平台签发的 token 权限。
- HTTP 429/5xx 或网络失败：本次发布失败，可重跑；不得把错误当作制品不存在而覆盖。
- Image source/revision/platform mismatch 或 Chart 身份不匹配：停止发布，检查 SHA、引用和 Package 内容，不自动删除旧制品。
- Chart Version Check 失败：相对准确 base 提升源码 version；不要添加 appVersion/hash 来绕过。如果历史缺失，先拉取完整历史。
- 发布镜像失败后 Chart 检查失败是预期门禁行为，优先排查上游；没有成功 artifact 就不宣称完整发布成功。

首次成功后，可在 main 分支规则中将上述六条名称设置为 required status checks。Runner 分钟数、缓存和 artifact 存储额度以当前 GitHub 账户用量页面为准。[GitHub Actions 计费文档](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
