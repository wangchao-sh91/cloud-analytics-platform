## 1. Chart 基础与配置契约

- [x] 1.1 准备并记录实际验证的 Helm 稳定版本，检查现有 kind 上下文及存储条件，不重建集群。
- [x] 1.2 创建 `charts/cap/`、Chart.yaml、默认 values、kind 和 legacy values、values.schema.json，明确数据库始终随 Chart 部署、单副本及持久化。
- [x] 1.3 实现默认 release 隔离命名及 legacy 命名 helpers，检查名称长度、选择器和不同 release 互不干扰。

## 2. PostgreSQL、凭据与数据保留

- [x] 2.1 模板化 PostgreSQL StatefulSet、内部 Service、ConfigMap、资源与探针；保留 data 卷模板，设置 PVC Retain 策略并校验 Kubernetes 版本要求。
- [x] 2.2 实现全新安装生成 Secret、升级和重新安装在线复用 Secret、必要字段检查及 keep 保留策略，不输出实际凭据。
- [x] 2.3 实现已有数据卷而凭据缺失时停止发布的检查，以及已有数据库名、用户、命名模式和存储设置的变更拒绝逻辑。
- [x] 2.4 为默认、kind、legacy 配置运行模板校验，验证 Secret 复用、缺失凭据、非法配置和保留策略的行为。

## 3. 迁移与应用启动

- [x] 3.1 实现按 release revision 命名的普通迁移 Job，包含有界数据库等待、迁移命令、任务超时、失败日志及当前 Job 保留策略。
- [x] 3.2 实现后端镜像中的初始化等待工具，检查指定迁移 Job 的成功/失败及目标 schema，支持超时和清晰错误，不在 API 副本中执行迁移。
- [x] 3.3 模板化 API Deployment、Service 和最小只读 Job RBAC，通过 revision 标记触发每次升级重新等待迁移，保留原存活和就绪检查。
- [x] 3.4 模板化前端 Deployment、Service 和 Nginx ConfigMap，代理对应 release 的 API，使用 checksum 触发配置更新并保留 SPA 路由及英文 NOTES。
- [x] 3.5 验证等待工具的数据库延迟、Job 成功/失败、Job 不存在、API 查询权限错误和超时行为，确认 schema 已达 head 时也不能绕过失败 Job。

## 4. kind 镜像准备与 Helm 发布入口

- [x] 4.1 拆出镜像构建和 kind 加载步骤，保留明确集群名、上下文一致性检查及唯一镜像 tag，构建包含等待工具的后端镜像。
- [x] 4.2 将部署入口调整为 Helm 安装/升级，显式传入 context、namespace、release、values 与有界等待，不再直接 apply 业务清单。
- [x] 4.3 提供在线只读预检，拒绝不兼容配置、未知资源冲突和错误归属；离线 lint/template 与在线集群检查边界明确。

## 5. 现有 cap-001 部署接管

- [x] 5.1 实现显式 legacy 接管流程，默认只检查；执行模式在修改前完成集群外备份，保存资产、PVC UID、Secret 散列和原资源归属基线。
- [x] 5.2 验证接管预检覆盖旧资源名、选择器、StatefulSet 不可变字段、数据库配置、卷绑定和 Helm 归属；备份失败或归属冲突时不得修改工作负载。
- [x] 5.3 对通过预检的目标资源设置归属元数据并以 legacy 模式安装，实测当前 cap 环境 PVC UID、凭据、资产和 CRUD 保持一致，保留失败诊断与恢复资料。
- [x] 5.4 接管验证成功后停用原 `infra/k8s/` 及脚本直接 apply 的独立发布入口，只清理明确识别的旧迁移完成任务，不触及 PVC 或其他 release。

## 6. 实际集群生命周期验收

- [x] 6.1 在现有 kind 的隔离命名空间验证全新安装及非默认 release 命名，通过本机回环 port-forward 运行既有浏览器 CRUD 测试。
- [x] 6.2 验证数据库延迟与迁移失败场景，确认无启动死锁、失败 Job 可诊断且目标 API 不就绪；失败场景只针对隔离测试 release。
- [x] 6.3 验证相同镜像 tag 的再次升级产生新迁移 Job、更新后所有组件就绪，并验证数据库及 API Pod 重建后资产和凭据保持不变。
- [x] 6.4 在隔离 release 中验证默认卸载保留 PVC 与 Secret、同身份重新安装复用原卷和凭据，逐字段比较资产及时间戳；检查普通工作负载和任务已删除。
- [x] 6.5 在隔离环境验证保留数据但 Secret 缺失时拒绝重新安装，恢复原 Secret 后可正常安装，不自动生成替代密码。
- [x] 6.6 验证同 namespace 不同默认命名 release 的服务、Pod、数据库和凭据隔离；验证不支持的存储、用户和数据库名升级变更被明确拒绝。

## 7. 文档与交付

- [x] 7.1 更新 README、Chart 使用说明和中文开发部署文档，给出镜像准备、Helm 安装/升级、values 配置、英文访问提示和准确工具版本。
- [x] 7.2 更新中文运维文档，覆盖接管、Secret/PVC 保留、卸载重装、失败诊断、备份恢复、schema 兼容回退及命名空间和集群删除边界。
- [x] 7.3 汇总静态与真实集群验收证据，核对任务与规格覆盖，执行 Helm lint/渲染检查和 OpenSpec 严格校验；不自动归档 cap-001 或 cap-002。
