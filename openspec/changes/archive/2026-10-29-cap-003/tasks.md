## 1. 本地质量检查入口

- [x] 1.1 为后端与 Python 发布脚本/测试添加 Ruff 开发依赖和正确性规则，更新 uv 锁文件并提供统一运行说明。
- [x] 1.2 为前端添加适用的 ESLint 配置及独立 lint/typecheck 命令，更新 npm 锁文件，保持现有 build 和 Playwright 入口。
- [x] 1.3 修复新启用规则发现的实际问题，验证检查覆盖源码且未整体忽略；限制修改范围，保持资产 API 和英文 UI 行为不变。

## 2. 无集群的测试与 Helm 校验

- [x] 2.1 整理后端 pytest 与现有发布预检查逻辑单元测试的可复现入口；为后端集成测试显式配置独立 TEST_DATABASE_URL，确认资产集成测试不会因缺少数据库配置被跳过；发布预检查逻辑单元测试使用 mock，不连接数据库或集群，也不执行部署。
- [x] 2.2 建立固定 Helm 版本与显式 Kubernetes 版本的校验入口，对默认、kind、legacy values 执行 lint/template 并运行现有 Chart 测试，不访问集群。
- [x] 2.3 使用临时 PostgreSQL 17 执行后端集成测试；另外在不提供数据库连接变量的情况下执行使用 mock 的发布预检查逻辑单元测试，确认其不连接数据库或集群。验证迁移/断言失败能返回非零状态，并确认 Helm 校验在没有 kubeconfig 时可运行。
- [x] 2.4 实现 Chart Version Check 的 PR 净改动检测和源码版本校验入口：从准确 base/head 获取 merge-base 与变更路径，代码相关改动要求 head version 按 SemVer 严格高于 base；文档豁免、缺基准失败和 main 不执行 PR 比较均有明确结果。

## 3. 制品版本与 Chart 暂存打包

- [x] 3.1 实现 PR/main 源 SHA 与发布身份生成入口，规范化 GHCR owner，镜像 tag 等于完整 SHA，Chart version 为源码 Chart version 加 `-sha<完整 SHA>`，run ID/attempt 仅用于元数据，不参与版本。
- [x] 3.2 实现 Chart 临时副本打包入口，写入本次前后端镜像 repository/tag、Chart version 和 SHA appVersion，保留源 Chart 与本地 values 不变。
- [x] 3.3 校验发布副本与打包产物，确认前端、后端及迁移容器绑定目标镜像；定义成功发布 JSON 清单字段和摘要格式，不包含凭据。
- [x] 3.4 为 Chart bump 的改动分类、删除/跨目录重命名、SemVer 数值比较、无 bump/回退失败、纯文档通过、缺失比较基准失败、PR/main SHA 选择、同 SHA 版本稳定、源文件不被改写及打包镜像一致性增加必要的离线回归测试。
- [x] 3.5 实现 GHCR 精确引用的存在性与来源校验：已存在且匹配则复用 digest，仅发布缺失项；鉴权/网络错误及来源或配置不一致明确失败，不覆盖已有版本，并验证部分发布后的恢复路径。

## 4. PR 与 main 自动发布 Workflow

- [x] 4.1 将现有入口拆为仅由目标 main 的 PR 触发的 ci.yaml 和仅由 main push 触发的 publish-main.yaml；使用标准 Linux Runner，固定 checkout 到事件对应 SHA，保留 PR 取消旧运行、main 独立发布及合理超时。main 文件严格只定义两个发布 Job。
- [x] 4.2 仅在 PR Workflow 配置 Static Checks、Code Tests、Helm Validation、Chart Version Check 四个并行 Job，使用锁定依赖、临时 PostgreSQL 健康检查与固定工具版本；main 不定义或调用这些检查，不展示其 skipped Job，也不启动 PostgreSQL service；PR 六条检查名保持稳定。
- [x] 4.3 两个入口复用 Build and Publish Images 逻辑：PR 四项检查通过后执行，main 无 PR 门禁依赖并直接执行；构建或复用 linux/amd64 前后端镜像，保留 OCI 标签、完整 SHA tag、digest 和同 SHA 串行策略。
- [x] 4.4 在两个入口配置 Package and Publish Chart Job，仅依赖各自镜像 Job；复用现有临时打包、OCI 推送、精确版本读回验收及发布清单/摘要逻辑，不因 main 精简 Job 而移除制品校验。
- [x] 4.5 分别实现依赖失败门禁：PR 四项质量检查任一失败阻止镜像发布，main 不读取或依赖 PR 质量结果；两者镜像失败均阻止 Chart 发布并明确失败。保留最小写权限、完整 Action SHA、统一 PR 路径和权限不足报错，不增加 Fork 分流。

## 5. 使用与准备文档

- [x] 5.1 更新中文 CI/GHCR 文档，明确 PR 六项检查、main 仅两个发布 Job 及二者触发/依赖关系，保留本地复现、collaborators-only 前提和 GHCR 权限/可见性排查说明。
- [x] 5.2 文档给出 Chart bump 的路径范围与比较规则、PR head/main 合并后 SHA 的镜像和 Chart 版本示例、幂等重跑、精确制品拉取方式、发布 JSON 示例及 artifact 保留期限，明确 head SHA 校验不等于合并预览校验。
- [x] 5.3 同步 docs/prepare.md 中 PR 六项检查与 main 两项发布的准备和验收步骤，保持 GitHub/GHCR 与后续部署准备的区分，明确部署、E2E、清理属于下一 change。

## 6. 发布验收与范围检查

- [x] 6.1 在 Workflow 拆分及契约测试更新后重跑本地静态检查、隔离数据库后端测试、mock 单元测试、Helm 校验及打包回归，确认既有本地配置和数据保留语义不变。
- [x] 6.2 分别校验两个 Workflow 的语法、表达式、触发、Job 数量和依赖/权限，确认 PR 六项、main 仅两项且无四个 skipped 检查、无数据库 service；未引入应用安装、集群变更、E2E、Flux 或清理入口。
- [x] 6.3 在可用的 GitHub/GHCR 远端条件下，由 collaborator 提交已 bump Chart version 的代码 PR 验收六项检查成功：按发布清单读取两项镜像和 Chart，核对其 SHA、版本、digest 与渲染内容，记录运行链接；未执行时明确保留为待验收。
- [x] 6.4 更新 Workflow 契约和门禁回归：PR 保留未 bump/失败时阻止发布，main 直接执行镜像发布且无 PR 质量门禁依赖，两者镜像失败均阻止 Chart；保留版本、权限与幂等回归，分别记录离线和远端结果。
- [x] 6.5 在 main push 后验收仅显示 Build and Publish Images 和 Package and Publish Chart 两个 Job，核对准确 main SHA 的制品及读回结果，确认无额外质量检查 Job、PostgreSQL service 或部署；记录真实运行链接，未具备条件时保留待验收。

## 验证记录

本地验收与维护者人工远端验收分别记录于 `docs/verification/cap-003.md`。本次 main 精简已完成 Workflow、契约测试和文档同步，本地静态检查、隔离测试、Helm 与 actionlint 验证通过。维护者已在本次会话确认任务 6.3、6.5 人工验证完成并勾选；远端结果依据维护者确认记录，未由本地代理执行，运行链接尚未附入记录。
