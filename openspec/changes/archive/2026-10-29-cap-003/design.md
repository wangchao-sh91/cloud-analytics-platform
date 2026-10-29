## Context

动机及业务范围见 `proposal.md`，行为契约见 `specs/ci-artifact-publishing/spec.md`。

- cap-003 既有实现使用单一 `.github/workflows/ci.yaml`，PR 与 main 都运行六个 Job；本次规划修订要求 PR 保留六项，main 仅运行两个发布 Job。后端使用 Python 3.12、uv 与 pytest，前端使用 Node 22、npm，已有本地静态检查入口。
- 后端资产集成测试会迁移、清空测试表，必须显式提供独立 `TEST_DATABASE_URL`；不能使用既有部署库。
- `scripts/tests/test_release.py` 是现有发布预检查逻辑的单元测试，使用 mock 验证资源归属冲突、数据库配置兼容性及备份失败时停止操作等安全边界，不连接数据库或 Kubernetes 集群，也不执行实际部署；`scripts/tests/test_chart.py` 通过 Helm 子进程验证 Chart。
- Chart 当前版本为 `0.3.0`，默认前后端镜像为 kind 本地镜像；values 支持镜像 repository/tag。将发布配置写回源码会干扰本地工作流。
- 现有 Playwright 测试依赖运行中的应用，不属于本次无部署流水线。没有独立前端单元测试，不将类型检查重复计作前端单元测试成功。
- cap-003 只生产制品；后续 Flux、PR 数据库重建、集群内 E2E、Checks 回报和手动清理在另一 change 中规划。
- 维护者确认仓库层已限制 collaborators-only 提交 PR。本设计以该限制为前提，不在 Workflow 中重复实现来源分类或 Fork 专门路径。

## Goals / Non-Goals

**Goals:**

- 六条稳定的 PR 检查与准确的源 SHA 对应；main 仅保留两个发布 Job，PR/main 复用制品发布脚本。
- 只使用标准 GitHub Linux Runner、临时 PostgreSQL 和 GHCR，运行前不需要集群或云账号准备。
- 制品具有唯一版本、完整身份和机器可读输出，可被后续独立部署流程消费。
- 检查、打包入口可以在本地复现；既有 kind/legacy 配置和数据保留语义不变。

**Non-Goals:**

- 不调用 Helm install/upgrade、kubectl 修改资源、Flux reconcile 或 GitOps 配置更新。
- 不引入 E2E、浏览器依赖、集群测试报告存储和 GitHub App。
- 不创建手动部署/清理 Workflow，不配置 OIDC/RAM/ACK；不修改数据库保留策略。
- 不添加前端单元测试框架、覆盖率门槛、多架构构建、签名或制品删除策略。

## Decisions

### 1. 分离 PR 检查与 main 发布 Workflow

PR 入口保留 `.github/workflows/ci.yaml`，只触发目标 main 的 `pull_request`（opened/synchronize/reopened），定义六个稳定 Job：

```text
Static Checks ───────┐
Code Tests ──────────┤
Helm Validation ─────┼──> Build and Publish Images ──> Package and Publish Chart
Chart Version Check ┘
```

main 入口单独放在 `.github/workflows/publish-main.yaml`，仅触发 main push，严格只定义两个 Job：

```text
Build and Publish Images ──> Package and Publish Chart
```

两个入口使用 `ubuntu-24.04` 标准 Runner，复用 `scripts/ci_release.py` 的身份、版本、镜像、Chart 发布及读回逻辑，保持两个发布 Job 的对外名称一致。main 不执行静态检查、代码测试、独立 Helm 校验或 Chart bump 检查，也不通过 skipped Job 展示这些步骤。发布 Job 内仍做准确 checkout、源码/版本格式校验、镜像身份校验、发布副本 lint/template、打包与实际制品读回；这些属于发布验收，不是额外质量检查 Job。

PR 的四项质量门禁并行，镜像 Job 用 `always()` 和显式结果判断阻止 failure/skipped/cancelled 上游触发推送。main 的镜像 Job 无 PR 门禁依赖，直接从该次 push 的准确提交构建或复用制品。两个入口的 Chart Job 都只依赖各自的镜像 Job，用 `always()` 加结果检查使镜像失败时 Chart 明确失败，不发布成功清单。

PR 以来源仓库和 PR 编号设置 concurrency group，可取消被更新替代的旧运行。main 不合并不同 push 的排队任务、不主动取消旧发布；镜像与 Chart 的同 SHA 发布锁继续生效。版本不使用浮动别名，实际部署顺序留给后续 change。

不使用路径过滤，以免纯文档 PR 缺少 required checks。维护者在 main 合并规则中配置 PR 六项 required checks；main 的两个发布 Job 不替代合并前门禁。

替代方案：在单一 Workflow 中为四个检查 Job 增加 PR 条件。未采用，因为 main 仍会显示四个 skipped Job，不能满足 main 只包含两个发布 Job 的要求。共享发布脚本避免两个入口的制品规则漂移；不创建会增加 main Job 数量的额外准备 Job。

### 2. 一次运行只读取一个源提交

PR 显式 checkout `pull_request.head.sha`，main checkout 事件中的 `github.sha`。不依赖 PR 默认的合并预览 ref，也不通过运行中可变分支名拉取源码。记录完整 SHA，并验证 checkout 后 HEAD 与记录一致。

直接使用 head SHA 保证后续能够按源提交追溯制品；它不等同于验证与最新 main 的合并结果。是否要求分支先更新到最新 main 属于仓库合并规则，可在文档说明，不能在摘要中暗示已测试合并预览。

所有身份数据使用结构化环境变量/参数传递和校验，避免把分支名等事件文本直接拼接进 shell 命令。GHCR owner 规范化为小写。

### 3. Chart 版本提升门禁与现有质量入口

新增独立 `Chart Version Check`。PR 获取事件中固定的 base/head SHA，补齐 Git 历史并定位 merge-base；变更列表来自 merge-base 到 head 的净差异，版本大小比较则读取事件 base SHA 和 head SHA 各自的 `charts/cap/Chart.yaml`。这样不把目标分支独有的文件变动误判成 PR 改动，也能发现目标分支已使用相同版本的情况。基准/历史缺失时明确失败，不回退为空差异而放行。

变更分类采用保守规则：`docs/**`、`openspec/**`、根目录 `.md` 文档以及根目录 `LICENSE`/`LICENSE.*` 为纯文档豁免，其余改动均要求 bump，包括 `apps/**`（含源码、测试、依赖、Dockerfile）、`scripts/**`、`charts/**`、`.github/**` 和根目录构建配置。新增、删除、重命名均检查；跨目录重命名同时考虑旧路径和新路径，不能将代码移到文档目录来绕过检查。路径由 Git 的 NUL 分隔输出解析，支持空格等字符，不使用不安全的 shell 拆词。

源码 version 首版限定为稳定 `MAJOR.MINOR.PATCH`，无前导零、prerelease 或 build metadata；按数值 SemVer 比较，head 必须严格大于 base。修改 appVersion 或仅依赖 CI 追加 hash 都不算 bump。仅文档 PR 的该 Check 成功并解释无需 bump，但仍执行其他检查及发布。同一个 PR 只需相对 base 提升版本，不要求每次追加 commit 都再次提升。main 不定义或调用 Chart Version Check，也不做 PR base/head 比较；发布元数据生成过程仍校验源码版本格式，并使用合并后的 SHA 发布。本地检查工具的 push 模式可保留，但 main Workflow 不调用该独立检查入口。

替代方案：将检查放入 Helm Validation。采用独立 Check，使维护者在 PR 上能直接识别未 bump 的原因，并单独设置 required check。


- Python：添加 Ruff 开发依赖及配置，覆盖 `apps/backend` 与 `scripts`，从正确性规则开始（例如 E4/E7/E9/F）；仅修复启用规则暴露的问题，避免批量格式重写。
- 前端：添加 ESLint 的 TypeScript/React 适用配置、`lint` 与独立 `typecheck` 命令；保留 build 行为和现有 Playwright 入口。
- 依赖安装使用 `uv sync --frozen`、`npm ci`，更新对应锁文件；工具及第三方 Actions 在实现时选择兼容版本并固定，Actions 引用经核对的完整 commit SHA。
- `Code Tests` 包含两类测试：从后端目录运行完整后端测试，其中集成测试连接有健康检查的临时 PostgreSQL 17 service，并显式接收该服务的 `TEST_DATABASE_URL`；另外执行 `scripts/tests/test_release.py` 中使用 mock 的发布预检查逻辑单元测试，后者不需要数据库连接变量、不连接数据库或集群，也不执行部署。数据库测试不得因缺环境变量被跳过。
- Helm Job 使用项目固定 Helm 3 工具版本（沿用安装入口时核对现有 3.19.0），在本地脚本与 CI 显式采用 `1.35.8` 离线渲染目标，满足当前 `kubeVersion` 限制。对默认、kind、legacy values 执行 lint/template，并执行 Chart pytest；不要求 kubeconfig，不执行 kubectl。

代码测试不包含 Playwright，也不额外为“前端测试”制造空入口。未来有真实前端单元测试后可扩展独立需求。

### 4. 使用 GITHUB_TOKEN，依托仓库协作者限制

Workflow 顶层 `contents: read`，只有镜像和 Chart 发布作业申请 `packages: write`。PR 与 main push 统一使用自动签发的 `GITHUB_TOKEN`，无需 `id-token: write`、`contents: write`、PAT 或云平台 Secrets。

仓库层的 collaborators-only 限制作为已由维护者配置的前提，Workflow 不根据 PR 是否来自 Fork 切换无推送构建或跳过 Chart 发布。保持标准 `pull_request` 事件，不为获取更高权限切换到 `pull_request_target`。仓库准入限制不改变 GitHub 实际签发的 token 权限；若平台或 Package 授权不足，按普通发布错误明确失败，不改用长期高权限凭据，也不将失败降为成功或跳过。

使用仓库 `GITHUB_TOKEN` 发布，将 Package 与源仓库关联，镜像附带 OCI source/revision 标签。已有 Package 缺少仓库访问权限时明确报错，文档指导维护者设置 Manage Actions access。保持 Registry 默认可见性，不自动公开；未来集群读取 Private 制品的凭据在后续 change 处理。

### 5. 基于完整提交 SHA 的确定性制品版本

owner 由仓库 owner 推导并转为小写，PR/main 使用同一公式：

```text
image-tag: <full-sha>
chart-version: <Chart.yaml version>-sha<full-sha>
appVersion: <full-sha>

# 源码 version 为 0.3.0 时
# PR:   ghcr.io/<owner>/cap-backend:<PR head SHA>
#       oci://ghcr.io/<owner>/charts/cap --version 0.3.0-sha<PR head SHA>
# main: ghcr.io/<owner>/cap-backend:<main merge SHA>
#       oci://ghcr.io/<owner>/charts/cap --version 0.3.0-sha<main merge SHA>
# frontend 使用同样的镜像 tag
```

PR 使用最新 head 的完整 40 位 SHA，main 使用对应 push 在 main 上的完整 SHA；merge commit、squash merge 或 rebase merge 都以 main 事件的实际 SHA 为准。run ID/attempt 仅保留在运行元数据和 artifact 名称中，不进入镜像 tag、Chart version。

Chart 后缀使用 `-sha<hash>`，保证是合法的 SemVer prerelease 标识，即使 hash 恰好全为数字也不会触发纯数字标识的前导零限制；不使用 `+` build metadata，避免 Helm OCI 的 tag 转换。后续部署消费精确版本，不按这个 hash 后缀的 SemVer 字典顺序推断提交先后。

同一 SHA 重跑时引用保持不变。发布前按精确引用检查 GHCR：已有镜像必须核对 source/revision 标签及目标架构，已有 Chart 必须读回核对版本、appVersion、镜像 repository/tag 和来源；验证通过则复用原 digest，只构建/发布缺失项。鉴权/网络错误不能当作不存在；已存在但来源或内容配置不一致则失败，不覆盖。Chart 增加源仓库和 revision 注解以便核对，不改变应用模板行为。

同一 SHA 的发布 Job 使用按 source SHA 的串行锁（允许同提交排队重跑，不主动取消运行中发布）；不同 SHA 可并行。PR 和 main 若恰好指向同一 SHA，复用该 SHA 制品是同源复用，不是冒充不同提交。没有跨对象事务，部分成功后重跑从缺失项恢复。首次发布后的相同 SHA 不因可变上游基础镜像而重建覆盖已有 tag；需要重建时产生新的源提交。

镜像 digest 记录于发布清单；Chart 默认 values 使用完整 SHA tag，无需新增 digest 模板字段。不发布 latest、浮动分支 tag，不向源码提交 CI 派生的 SHA 后缀。

### 6. 临时打包并验收实际制品

复用两个现有 Dockerfile 构建 linux/amd64 镜像（对应当前学习目标的 x86 节点），不额外镜像官方 PostgreSQL。两个镜像都推送成功后，才开始 Chart 发布。

在镜像或 Chart 引用不存在、确实需要首次发布时，复制 `charts/cap` 到临时目录，结构化更新 Chart version/appVersion 和前后端默认 repository/tag；保留 PostgreSQL 配置以及 kind/legacy 文件。发布默认 values 在临时副本中进行 lint/template，检查后端 Deployment、迁移容器、前端 Deployment 确实使用目标镜像，然后 `helm package`。

推送目标使用 `oci://ghcr.io/<owner>/charts`（不包含 `cap` 或版本），Chart 名和 tag 由包推导。推送后按精确版本拉回，核对 Chart version/appVersion、两项镜像配置及 OCI digest，再渲染拉回的包。只有所有验收成功才输出成功发布清单。

不追求跨三个 Registry 对象的事务。部分推送失败时可能留下唯一版本镜像或 Chart，但运行失败且没有完整发布清单；重跑验证已有引用并补齐缺失项，不改变版本。制品垃圾清理留待后续，不在失败路径删除已有 Package。

### 7. 发布清单作为后续部署接口

完整发布后生成无凭据的 JSON 文件与 Actions Summary，清单至少包括：

- `schema_version`（首版为 1）、仓库、事件、渠道（pr/main）、PR 编号（适用时）、源码 Chart 基准版本；
- 完整源 SHA、run ID、attempt、运行 URL；
- 前后端 image repository/tag/digest；
- Chart OCI 地址、SemVer version、OCI manifest digest。

上传独立命名的发布清单 artifact，建议保留 7 天；失效后仍可凭记录的 GHCR 版本读取制品。失败运行提供诊断摘要，不输出标记成功的清单。每个 Action artifact 按 run/attempt 隔离，不把明文凭据或随机数据库密码包含在清单或命令输出中。

后续 change 可以消费该接口，但本 change 不写入 GitOps 仓库、不创建 Flux 资源、不回报集群部署结果。当前 GHCR 推送/read-back 通过 `GITHUB_TOKEN` 即可，不需要实际购买 Runner ECS。

## Risks / Trade-offs

- [PR 验证 head 而非合并预览] → 摘要明确 source SHA，仓库规则可要求及时更新分支；main 仅发布，质量保障依赖合并前 PR 门禁。
- [SHA tag 在 Registry 层仍可被有权用户覆盖] → 工作流先核对已有制品且不复写，记录镜像及 Chart digest，后续消费者可据 digest 验证。
- [运行 token 或 Package 授权不足] → 发布明确失败并说明所缺权限；不改变仓库准入规则、不引入专门的来源分流或高权限事件绕过。
- [部分制品已推送但后续失败] → 不产出成功清单，版本与源 SHA 固定绑定，允许幂等重跑，不将残留对象视为可部署成功版本。
- [旧代码 lint 问题扩大 diff] → 以正确性规则起步，限量修复，不引入全仓格式变更或跳过所有源码。
- [私有仓库 Runner 分钟数、artifact 存储及 GHCR 网络故障] → 使用标准 Linux Runner，避免 E2E/集群依赖；发布日志区分网络和权限错误，文档解释额度及短期 artifact 保留。
- [离线 Helm 检查不能验证真实集群行为] → 文档仅声明渲染/打包验证，部署与 E2E 作为下一 change 的验收。

## Migration Plan

1. 添加本地质量检查入口、锁文件和仅必要的源码修复，先本地运行现有测试及 Helm 校验。
2. 复用现有 PR 改动检测、SHA 元数据生成和发布脚本，拆分六 Job PR Workflow 与两个 Job main Workflow，更新 Workflow 契约测试。
3. 由 collaborator 提交测试 PR 验证六项成功，下载发布清单，按引用读取镜像及 Chart；执行代码未 bump/正确 bump/纯文档、失败门禁、权限不足报错与相同 SHA 幂等重跑验证。
4. PR 合并后确认 main 运行只显示两个发布 Job，对照合并后 SHA 和制品读回结果；验证未运行四项 PR 检查或启动 PostgreSQL service，无需云凭据、kubeconfig 或自托管 Runner。
5. 首次成功后由维护者配置六条 required checks，并按需要调整 Package 仓库访问权限、可见性；不自动修改这些账户设置。
6. 回退时恢复上一版 Workflow/检查配置；已发布的唯一版本保留，不需要数据库迁移、集群回退或 main spec 直接修改。

参考：
- [GitHub Packages 与 Actions 权限](https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions)
- [GitHub Workflow 事件与 PR 权限](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Helm 3 OCI Registry](https://docs.helm.sh/docs/v3/topics/registries/)
