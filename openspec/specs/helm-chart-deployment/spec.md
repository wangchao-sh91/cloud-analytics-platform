# helm-chart-deployment Specification

## Purpose

为 Lab Dell PowerEdge 物理机管理平台提供统一的 Helm 发布能力，将前端、API 和 PostgreSQL 一起部署到 Kubernetes，并支持现有 kind 部署的安全接管、配置覆盖、数据库迁移、升级及保留数据后的卸载和重新安装。

## Requirements

### Requirement: 单 release 完整部署

项目 SHALL 提供可在现有 kind 集群安装的 Helm Chart，由单个 release 部署前端、API、单副本 PostgreSQL、数据库迁移任务及必要的配置、凭据和内部服务。PostgreSQL SHALL 随 Chart 部署，本次 SHALL 不提供外部数据库模式。部署 SHALL 使用明确指定的 Kubernetes 上下文和命名空间，不重新创建集群。

#### Scenario: 全新安装
- **WHEN** 镜像已准备好，维护者在具有可用存储的空命名空间安装 Chart 并等待完成
- **THEN** PostgreSQL、API、前端和迁移任务按依赖条件完成启动，release 成功且资产 CRUD 可用

### Requirement: 参数化配置与隔离

Chart SHALL 提供默认 values、kind 专用 values 和配置说明，支持覆盖前后端及数据库镜像、拉取策略、前后端副本数、资源配额，以及首次创建持久卷时使用的存储类和容量。数据库副本数 SHALL 固定为 1；默认资源命名和选择器 SHALL 隔离不同 release。参数无效或不支持的已有数据库配置变更 SHALL 明确失败，不通过替换数据库或 PVC 达成变更。

#### Scenario: kind 配置覆盖
- **WHEN** 维护者使用 kind values 并指定本地已加载的应用镜像 tag
- **THEN** 渲染和实际部署使用指定镜像和资源配置，无需编辑模板

#### Scenario: release 隔离
- **WHEN** 同一命名空间安装两个采用默认命名规则的不同 release
- **THEN** 各自的服务仅选择对应的 Pod，数据库卷和凭据互不覆盖

#### Scenario: 不支持的持久化变更
- **WHEN** 升级尝试改变已部署数据库的存储类、卷模板容量、数据库名或用户名
- **THEN** 发布流程提示需要独立迁移或扩容流程并停止，不重建数据库或卷

### Requirement: 迁移完成后启动 API

每次安装或升级 SHALL 运行独立的数据库迁移任务，等待数据库可连接后执行迁移。API SHALL 在目标 schema 版本可用后才启动提供服务；前端、API、数据库的资源创建顺序 SHALL 不导致迁移与就绪检查互相等待。数据库等待和迁移 SHALL 有明确的超时和可查看的失败日志。

#### Scenario: 数据库延迟就绪
- **WHEN** 首次安装期间 PostgreSQL 初始化较慢
- **THEN** 迁移等待数据库可连接，API 等待目标 schema，待迁移成功后发布可以完成

#### Scenario: 迁移失败
- **WHEN** 迁移命令失败或等待数据库超时
- **THEN** 发布不能报告成功，目标 API 不进入就绪状态，维护者可以查看失败任务日志，原数据和凭据不被自动删除

#### Scenario: 再次升级
- **WHEN** 维护者在同一镜像版本下发起新的 release 升级
- **THEN** 本次升级仍执行独立迁移检查，不因镜像 tag 相同而复用之前的完成结果

### Requirement: 稳定且可保留的数据库凭据

全新安装且没有已有数据时，Chart SHALL 创建数据库凭据，并通过 Secret 注入 PostgreSQL、迁移任务和 API。升级、卸载后同 release 同命名空间重新安装 SHALL 复用已有凭据，不自动轮换密码。源码、示例 values、日志和普通部署输出 SHALL 不包含实际凭据。若发现已有数据卷但所需 Secret 缺失或不完整，发布 SHALL 在修改工作负载前失败，要求维护者恢复正确凭据。

#### Scenario: 升级复用密码
- **WHEN** 已安装 release 执行升级或重新安装
- **THEN** 数据库凭据字节保持不变，API 与迁移仍可连接原数据库

#### Scenario: 数据卷存在但凭据缺失
- **WHEN** 数据卷仍在而数据库 Secret 不存在或缺少必要字段
- **THEN** 安装或升级明确失败，不生成新的随机密码，也不初始化替代数据库

### Requirement: 卸载后保留数据并支持重新安装

默认卸载 SHALL 删除应用和数据库工作负载及本 release 的普通服务、配置和迁移任务，保留数据库 PVC 与所需凭据，且不删除命名空间。使用同一 release 名称、命名空间、命名模式和兼容数据库配置重新安装 SHALL 复用原 PVC 和凭据，保留资产 ID、内容和时间戳。文档 SHALL 明确删除命名空间、PVC 或 kind 集群的数据销毁边界。

#### Scenario: 卸载并重新安装
- **WHEN** 已有测试资产的 release 默认卸载，之后以原身份和兼容配置重新安装
- **THEN** PVC 和 Secret 保留且没有被替换，原资产全部字段可通过 API 读取

#### Scenario: 不同身份重新安装
- **WHEN** 维护者更换 release 名称或命名空间尝试重新安装
- **THEN** 文档明确这属于新的部署，不承诺自动连接旧数据，原保留数据不被清除

### Requirement: 安全接管已有 cap-001 部署

项目 SHALL 提供显式的现有部署接管流程，默认不自动接管同名资源。流程 SHALL 先备份数据库到集群外并检查目标上下文、资源身份、数据库配置、PVC、Secret 以及现有 release 归属；确认兼容后才将目标工作负载交给 Helm 管理。接管 SHALL 复用原 PostgreSQL 实例对应的 PVC、数据库名、用户及凭据，保留原资产，且不依赖删除重建 StatefulSet 或修改其不可变字段。

#### Scenario: 成功接管
- **WHEN** cap-001 的已有资源通过预检，备份成功并执行显式接管
- **THEN** Helm release 管理目标工作负载，原 PVC UID 和凭据保持不变，资产记录与接管前一致

#### Scenario: 资源归属冲突
- **WHEN** 同名资源属于另一个 release，或实际资源与预期清单不兼容
- **THEN** 接管在修改归属或工作负载前停止并报告原因，不强制覆盖或夺取资源

#### Scenario: 备份失败
- **WHEN** 接管前的数据库备份失败
- **THEN** 流程停止，不修改任何资源的 Helm 归属或替换工作负载

### Requirement: 同源访问及业务兼容

Chart 部署 SHALL 保留英文 UI、中文资产内容及既有 `/api/servers` 契约；通过绑定本机回环地址的 port-forward 提供页面和 API 同源入口。前端 SHALL 使用当前 release 对应的 API 地址，数据库仅提供集群内部服务。首版无登录的本地使用边界 SHALL 保持明确。

#### Scenario: 带 release 名的服务
- **WHEN** 使用非默认 release 名称安装，并通过其前端服务访问
- **THEN** 页面和 API 均可用，Nginx 不会将请求发送到其他 release 或固定名称的旧 API

### Requirement: 单一部署来源与 kind 镜像准备

项目 SHALL 将镜像构建、kind 镜像加载与 Helm 资源发布分开，保留本地镜像准备步骤，并将 Helm 作为受支持的部署入口。原始清单和直接 apply 逻辑 SHALL 被移除或仅作为有明确限制的迁移资料，不再作为并行维护的发布方式。项目 SHALL 提供中文安装、升级、失败排查、备份恢复、接管和卸载重装文档，记录验证过的 Helm 版本。

#### Scenario: 开发者部署
- **WHEN** 维护者按照文档构建、加载镜像并执行 Helm 安装或升级
- **THEN** 不需要手动替换 YAML 字符串或另行执行原始 kubectl apply 发布流程

### Requirement: 发布失败与应用回退

发布失败 SHALL 保留数据及可诊断信息；应用回退 SHALL 仅在确认 schema 兼容后执行，不把 Helm 回退视为数据库迁移回退。持久化、凭据保留、迁移失败、同源 CRUD 和已有部署接管 SHALL 具有可重复的验收记录。

#### Scenario: schema 不兼容的回退
- **WHEN** 目标旧应用不兼容当前数据库 schema
- **THEN** 运维流程停止直接应用回退并要求使用经验证的恢复方案，不自动执行删除数据的 downgrade
