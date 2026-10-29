## Purpose

为项目提供独立于 Kubernetes 集群的 PR 质量检查和 GHCR 制品发布能力，使维护者能够判断代码与 Chart 是否可构建，并准确定位同一提交对应的前后端镜像和 Helm Chart，为后续部署流程提供可追溯的输入。

## ADDED Requirements

### Requirement: PR 六项检查

系统 SHALL 在目标为 main 的 PR 创建、更新提交或重新打开时产生六条名称稳定的检查：`Static Checks`、`Code Tests`、`Build and Publish Images`、`Helm Validation`、`Package and Publish Chart`、`Chart Version Check`。同一次运行的检查与制品 SHALL 对应 PR 的同一个 head commit SHA，而非混用合并预览提交与分支最新提交。前置检查失败时，下游发布 SHALL 不执行且 SHALL 不被报告为成功发布。

#### Scenario: 协作者 PR 成功
- **WHEN** collaborator 向 main 提交 PR，且本次提交的检查、构建及发布均成功
- **THEN** PR 显示六条成功检查，并可从运行摘要定位该 head SHA 的镜像和 Chart

#### Scenario: 前置检查失败
- **WHEN** 静态检查、代码测试、Helm 校验或 Chart 版本检查失败
- **THEN** 对应检查失败，下游发布不执行，其检查不以成功结果掩盖前置失败

#### Scenario: PR 运行期间分支更新
- **WHEN** PR 在运行期间收到新提交
- **THEN** 每次运行均使用各自记录的 head SHA，不将旧提交的成功结果或制品标记为新提交的结果

### Requirement: 代码改动必须提升 Chart 版本

`Chart Version Check` SHALL 基于本次 PR 的准确 base/head SHA，判断从共同祖先到 head 的净改动。代码改动包含应用、测试、依赖、Dockerfile、脚本、Chart、CI 及构建配置的新增、修改、删除或重命名；纯 `docs/`、`openspec/`、根目录 Markdown 文档或根目录 LICENSE 文件改动 SHALL 不强制 bump。任何未被明确归类为纯文档的文件 SHALL 按代码相关改动处理，跨目录重命名 SHALL 同时检查旧路径和新路径。存在代码相关改动时，head 中 `charts/cap/Chart.yaml` 的 version SHALL 按 SemVer 严格高于事件 base SHA 中的 version，不能仅修改 appVersion 或添加 SHA 后缀代替版本提升。源码 version SHALL 使用稳定的 `MAJOR.MINOR.PATCH` 格式；无法读取比较基准或解析版本时 SHALL 失败。无代码改动时检查 SHALL 成功并说明不要求 bump，而不是缺失 Check。

#### Scenario: 代码改动没有提升版本
- **WHEN** PR 修改应用源码，但 base 和 head 的 Chart version 都为 `0.2.0`
- **THEN** Chart 版本检查失败，镜像和 Chart 不发布

#### Scenario: 版本按 SemVer 提升
- **WHEN** PR 存在代码改动，base version 为 `0.2.9`，head version 为 `0.2.10`
- **THEN** Chart 版本检查通过，比较不采用字符串排序

#### Scenario: 仅修改文档
- **WHEN** PR 仅修改明确豁免的文档或 OpenSpec 规划文件
- **THEN** Chart 版本检查成功并说明无需 bump，其他检查及发布照常执行

#### Scenario: 同一 PR 后续提交
- **WHEN** PR 已将版本提升到高于本次 base 的版本，之后继续修改代码而未再次提升版本
- **THEN** 比较该 PR 的 base/head 后版本检查仍可通过，不要求每个 commit 都单独 bump

### Requirement: 本地可复现的静态检查

系统 SHALL 提供可在本地和 CI 使用的 Python 静态检查、前端静态检查及 TypeScript 类型检查入口。检查 SHALL 覆盖应用源码及仓库自有 Python 发布脚本和相关测试，排除依赖与生成目录；发现未定义符号、无效语法或类型错误等所配置规则问题时 SHALL 返回非零状态。不得通过全面忽略现有源码使检查空跑。

#### Scenario: 静态问题被阻止
- **WHEN** 检查范围内引入违反已配置规则的 Python/前端代码或 TypeScript 类型错误
- **THEN** 本地入口和 `Static Checks` 均失败，并输出可定位到文件的问题

### Requirement: 隔离的代码测试

`Code Tests` SHALL 执行现有后端测试，以及现有发布预检查逻辑的单元测试。后端集成测试 SHALL 使用本次作业创建的独立 PostgreSQL 17 测试库，等待数据库就绪并运行所需迁移；发布预检查逻辑的单元测试 SHALL 使用 mock 模拟外部命令结果，不连接数据库或 Kubernetes 集群，也不执行实际部署。所有测试 SHALL 不读取部署环境数据库凭据、不连接现有业务数据库或 Kubernetes 集群。浏览器 E2E SHALL 不纳入本 change 的代码测试。

#### Scenario: 数据库集成测试
- **WHEN** 作业执行资产 CRUD、约束与迁移相关测试
- **THEN** 所有写入和清表仅作用于作业内临时测试库，断言失败导致检查失败

#### Scenario: 数据库不可用
- **WHEN** 临时数据库未在规定时间内就绪，或迁移、测试失败
- **THEN** `Code Tests` 失败并保留作业诊断输出，不改连其他数据库绕过失败

#### Scenario: 发布预检查逻辑的单元测试
- **WHEN** 执行资源归属冲突、数据库配置兼容性及备份失败等发布预检查逻辑的单元测试
- **THEN** 使用 mock 模拟资源和外部命令结果，不连接数据库或集群、不修改实际资源，断言失败导致检查失败

### Requirement: 离线 Helm 校验

`Helm Validation` SHALL 对 Chart 的默认、kind、legacy 配置执行 lint 与模板渲染，并执行现有 Chart 测试。渲染 SHALL 明确指定与 Chart 支持范围相符的 Kubernetes 版本，不依赖 Runner 默认版本或在线集群。有效配置 SHALL 成功，已有非法参数场景 SHALL 继续失败；渲染成功 SHALL 不被表述为已完成安装或运行时验收。

#### Scenario: 受支持 values
- **WHEN** 检查默认 values、kind values 和 legacy values
- **THEN** 全部 lint 和 template 成功，既有命名隔离、参数拒绝及资源保留测试通过

#### Scenario: 无集群执行
- **WHEN** Runner 不存在 kubeconfig，且没有 Kubernetes 访问凭据
- **THEN** Helm 校验仍可完成，不调用实际安装、升级或资源修改操作

### Requirement: GHCR 应用镜像发布

在质量检查通过后，系统 SHALL 使用本次 SHA 的前后端 Dockerfile 构建 linux/amd64 镜像，分别推送到仓库 owner 下的 GHCR Package。镜像 tag SHALL 等于完整源 commit SHA，不添加 PR/main 前缀、run ID 或 attempt，且 SHALL 记录实际 digest；一个应用构建或推送失败 SHALL 导致检查失败且阻止 Chart 发布。系统 SHALL 不自动改变 Package 可见性。

#### Scenario: 前后端镜像发布
- **WHEN** PR 或 main 运行完成两项镜像推送
- **THEN** 两个镜像均可通过摘要中的精确引用获取，且源提交标签与本次 SHA 相同

#### Scenario: 部分镜像发布失败
- **WHEN** 后端或前端镜像构建或推送失败，即使另一个镜像已推送
- **THEN** 检查失败且不发布 Chart，不把部分制品视为完整成功版本

### Requirement: 与镜像绑定的 OCI Chart 发布

系统 SHALL 在两项镜像发布成功后，将本次源代码中的 Chart 复制到临时打包目录，写入同次提交的前后端镜像仓库和完整 SHA tag，设置发布版本为 `<源码 Chart version>-sha<完整源 SHA>`、appVersion 为完整源 SHA，再校验、打包并推送 GHCR OCI Registry。系统 SHALL 校验从 Registry 读回的 Chart 版本、镜像配置和 digest。打包 SHALL 不修改源码中的 Chart 默认版本、本地镜像配置或 kind/legacy values，不提交生成的版本变更；维护者在 PR 中手动提升源码 version 与打包追加 SHA 是不同操作。

#### Scenario: 打包与读回一致
- **WHEN** `Package and Publish Chart` 成功
- **THEN** GHCR 的 Chart 可以按摘要中的版本读取，appVersion 对应源 SHA，前后端镜像与本次镜像发布结果一致

#### Scenario: 读回失败
- **WHEN** Chart 已推送，但读取、元数据比对或发布配置渲染失败
- **THEN** 检查失败，运行摘要明确本次未完成完整发布验收

#### Scenario: 重跑同一提交
- **WHEN** 同一提交被重新运行
- **THEN** 镜像 tag 和 Chart 版本保持不变；验证并复用已存在的同源制品，仅构建或发布缺失项，不覆盖已有版本，元数据不一致时明确失败

#### Scenario: 已存在制品不匹配
- **WHEN** 精确版本的已有制品来源、revision、架构或 Chart 镜像配置与预期不符，或无法确认引用是否存在
- **THEN** 发布失败，不将鉴权或网络错误视为不存在，不覆盖或删除已有制品

### Requirement: main 自动发布

系统 SHALL 在 main 分支 push 时对该次 push 的准确 SHA 执行质量检查，并自动构建、发布前后端镜像和 OCI Chart。镜像 tag SHALL 等于该 main SHA，Chart 发布版本 SHALL 为该提交 `Chart.yaml` 的 version 加 `-sha<main SHA>`。PR 合并后的发布 SHALL 使用 main 上实际产生的提交 SHA，不再额外要求在 main 发布作业中修改版本，也不得将合并前 PR 的镜像冒充合并后提交的构建结果；PR 阶段的 base/head bump 比较 SHALL 不在 main 作业中错误重做。

#### Scenario: 合并 PR
- **WHEN** PR 合并产生 main push
- **THEN** 系统为 main 上该次提交重新构建并发布一套可追溯制品，不部署到任何环境

#### Scenario: main 检查失败
- **WHEN** main 发布的任一质量门禁失败
- **THEN** 运行失败且不发布完整 Chart，不连接集群尝试补偿或部署

### Requirement: 发布权限与仓库协作者边界

系统以维护者已在仓库层限制 collaborators-only 提交 PR 为前提。只读检查 SHALL 使用只读仓库权限，GHCR 推送 SHALL 仅向镜像与 Chart 发布作业授予必要的 Package 写权限，使用自动签发的 `GITHUB_TOKEN`，不需要云平台凭据、长期 PAT 或 Kubernetes 身份。系统 SHALL 对进入流水线的 PR 统一执行六项检查与发布，不按 Fork 来源实现只读构建、跳过推送或其他专门路径。系统 SHALL 不通过高权限事件或长期高权限凭据绕过平台实际授权。

#### Scenario: 统一 PR 流程
- **WHEN** collaborator 提交符合仓库准入规则的 PR
- **THEN** 运行统一的六项检查与发布流程，不因 PR 来源分类主动跳过镜像或 Chart 推送

#### Scenario: 发布未授权
- **WHEN** GHCR 写权限或 Package 的仓库访问授权不足
- **THEN** 发布明确失败并提供排查提示，不要求添加云账号管理员权限或暴露凭据

### Requirement: 发布结果与范围边界

系统 SHALL 在运行摘要及可下载的机器可读发布清单中记录事件、源 SHA、PR 编号（适用时）、运行编号与 attempt、两项镜像引用及 digest、Chart OCI 地址、版本及 digest。发布清单 SHALL 仅在完整发布验收通过后作为成功结果输出，不包含凭据。工作流 SHALL 不部署应用、不执行浏览器 E2E、不创建或清理测试环境、不修改 Flux/GitOps 期望状态。

#### Scenario: 后续部署读取制品
- **WHEN** 维护者或后续自动化读取成功运行的发布清单
- **THEN** 可准确定位同次源提交的镜像及 Chart，不需要猜测 latest 或分支浮动版本

#### Scenario: 无云端准备
- **WHEN** 仓库仅具备 GitHub Actions 与 GHCR 权限，没有 ACK、Flux、自托管 Runner 或云端密钥
- **THEN** 本 change 的 PR 检查及 main 发布仍可完整执行
