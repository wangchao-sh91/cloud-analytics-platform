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

- [x] 4.1 新增目标 main 的 PR 与 main push 触发入口，使用标准 Linux Runner；固定 checkout 到事件对应 SHA，配置 PR 取消旧运行、main 独立发布及合理超时。
- [x] 4.2 配置 Static Checks、Code Tests、Helm Validation、Chart Version Check 四个并行 Job，使用锁定依赖、临时 PostgreSQL 健康检查与固定工具版本；bump 检查获取准确 Git 历史，main 不重复 PR 比较；六条检查名保持稳定。
- [x] 4.3 配置 Build and Publish Images Job，前置四项检查通过后构建或复用 linux/amd64 前后端镜像，写入 OCI source/revision 标签，以完整 SHA tag 推送 GHCR 并输出 digest；同 SHA 发布串行，任一镜像失败阻止 Chart 发布。
- [x] 4.4 配置 Package and Publish Chart Job，临时打包并推送 OCI Chart，按精确版本读回校验元数据、镜像配置、digest 与渲染结果，成功后上传发布清单并写 Actions Summary。
- [x] 4.5 实现显式依赖失败门禁，确保下游检查不因自动 skipped 而掩盖失败；检查写权限只位于所需发布 Job，并固定外部 Actions 的完整 commit SHA。所有 PR 使用同一发布路径，权限不足明确失败，不增加 Fork 分流或高权限事件绕过。

## 5. 使用与准备文档

- [x] 5.1 增加中文 CI/GHCR 文档，说明六项 Check、本地复现命令、仓库层 collaborators-only 前提、main 发布、GHCR 初次创建/权限/可见性和常见失败排查。
- [x] 5.2 文档给出 Chart bump 的路径范围与比较规则、PR head/main 合并后 SHA 的镜像和 Chart 版本示例、幂等重跑、精确制品拉取方式、发布 JSON 示例及 artifact 保留期限，明确 head SHA 校验不等于合并预览校验。
- [x] 5.3 修订 docs/prepare.md，将本次必需的 GitHub/GHCR 准备与后续部署准备区分，去除本次依赖 ACK、OIDC、自托管 Runner 的暗示，并明确部署、E2E、清理属于下一 change。

## 6. 发布验收与范围检查

- [x] 6.1 运行全部本地静态检查、使用隔离数据库的后端集成测试、使用 mock 的发布预检查逻辑单元测试、Helm 校验及打包回归测试，确认源码 Chart、本地 kind/legacy values 和数据库保留语义未被发布流程改写。
- [x] 6.2 校验 Workflow 语法、表达式和 Job 依赖/权限，检查仓库中未引入任何 Helm 安装、集群变更、E2E、Flux 或清理环境入口。
- [ ] 6.3 在可用的 GitHub/GHCR 远端条件下，由 collaborator 提交已 bump Chart version 的代码 PR 验收六项检查成功：按发布清单读取两项镜像和 Chart，核对其 SHA、版本、digest 与渲染内容，记录运行链接；未执行时明确保留为待验收。
- [x] 6.4 验证代码未 bump 时阻止发布、纯文档无需 bump、发布权限不足时明确失败、PR 新 SHA 生成新版本、同 SHA 重跑复用匹配制品/补齐缺失项且不覆盖；可离线验证逻辑与远端实测结果分别记录，不将模拟执行等同真实 GHCR 发布。
- [ ] 6.5 在 main push 后验收准确 main SHA 的检查及镜像/Chart 发布，确认运行未访问集群且没有部署；记录运行链接和制品，未具备远端条件时保留为待验收。

## 验证记录

本地验收与未执行的远端验收分别记录于 `docs/verification/cap-003.md`。任务 6.3、6.5 等待实际 GitHub PR/main 运行及 GHCR 发布读回，不以模拟结果替代。
