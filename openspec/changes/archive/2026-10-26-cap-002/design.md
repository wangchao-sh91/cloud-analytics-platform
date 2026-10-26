## Context

动机见 proposal.md，行为契约见 `specs/helm-chart-deployment/spec.md`。本变更跨越 Chart、脚本、启动等待与运维生命周期，需要独立设计。

当前 `scripts/deploy.sh` 将构建、镜像加载、Secret 创建、数据库启动、迁移和应用发布串联；原始资源位于 `infra/k8s/`。数据库为 PostgreSQL 17，StatefulSet 名为 `postgres`，卷模板为 `data`，实际 PVC 为 `data-postgres-0`，Secret 为 `database-secret`。API 的就绪检查要求数据库 schema 等于当前镜像的 Alembic head。前端镜像 Nginx 写死 `api:8000`。

`cap-001` 已完成但未归档，主规格尚为空。本变更新增 Helm 能力并引用既有业务行为，不修改 `cap-001`、不自动同步或归档其规格。

## Goals / Non-Goals

**Goals:**
- 一个 Chart、一个 release 管理前端、API、单副本数据库与迁移生命周期。
- 明确区分全新安装与已有部署接管，同时使升级、默认卸载和同身份重新安装保留资产数据和凭据。
- 在现有 kind 集群上验证真实生命周期，并保留离线渲染与配置检查能力。

**Non-Goals:**
- 外部数据库、数据库高可用、自动密码轮换、PostgreSQL 大版本升级、在线存储扩容和公网入口。
- 自动数据库降级或把 Helm 回退等同于数据回退。
- 本次规划阶段修改应用、安装 Helm 或操作集群。

## Decisions

### 1. 自包含 Chart，拆分镜像准备与发布

采用 `charts/cap/`，包含 `Chart.yaml`、`values.yaml`、`values-kind.yaml`、`values-legacy.yaml`、`values.schema.json`、`templates/` 和 `README.md`。templates 覆盖命名 helpers、前后端 Deployment/Service、数据库 StatefulSet/Service、数据库配置与 Secret、Nginx ConfigMap、迁移 Job、API 等待用 ServiceAccount/Role/RoleBinding 及英文 NOTES。

数据库模板直接维护在本 Chart 中，使用官方 PostgreSQL 17 镜像，不增加第三方 PostgreSQL 子 Chart；现有资源结构简单且需要兼容既有 StatefulSet 的不可变字段，直接模板化更易验证接管和卷生命周期。数据库始终启用，保持 1 个副本。

镜像构建和 kind 加载放在独立准备脚本，保留显式集群名和上下文检查。`scripts/deploy.sh` 改为薄包装或由文档中的 Helm 命令替代，不再创建第二套资源或替换 YAML 字符串。接管完成前保留原始清单作为预检比对依据，完成后移除独立发布用途并标记历史迁移资料；不修改 `cap-001` 历史文档。

实施时选定并记录一个受支持的 Helm 稳定版本，对该版本运行所有验收；Chart 使用 API v2，不依赖强制接管参数。常规命令使用显式 `--kube-context`、release、namespace、values、超时和等待 Job 完成的选项。

### 2. values 与资源命名

| 配置组 | 主要内容 |
|---|---|
| `frontend` | image repository/tag/pullPolicy、replicas、resources |
| `backend` | image repository/tag/pullPolicy、replicas、resources |
| `database` | PostgreSQL 17 镜像、database/user、resources、persistence.storageClass/size |
| `migration` | 数据库等待超时、任务总超时与重试上限 |
| `naming` | `release` 默认模式或显式 `legacy` 接管模式 |

默认名称采用 `<release>-cap-<component>`，长度按 Kubernetes 命名限制处理；选择器使用 release 与 component，且同名 release 不允许通过改 namespace 外的资源交叉连接。legacy 模式固定使用旧资源名和旧选择器 `app: api/frontend/postgres`，仅用于单个已识别的旧部署。普通模式不使用这些旧 `app` 标签值，避免被 legacy Service 错选。legacy 模式一旦使用不能通过正常 upgrade 改为 release 模式。

kind values 使用本地应用镜像、IfNotPresent、单副本和适合本地的资源配额；镜像 tag 明确传入。storageClass 为空表示使用集群默认类，容量默认 2Gi。用户名、数据库名、命名模式、卷模板及存储设置在创建后保持稳定；预检比较 live 资源，拒绝在普通升级中修改这些设置，不实现隐式扩容或数据库迁移。

values schema 校验类型、必填镜像、正容量与资源相关输入，不提供关闭持久化或外部数据库开关。命名模式、Secret 与数据卷状态等集群条件另由在线预检检查；离线 lint/template 仅验证静态配置，不能替代在线检查。

### 3. 普通迁移 Job 与 API 等待，避免 hook 死锁

采用普通 Job，名称包含 release 与 `.Release.Revision`，不使用 pre-install/post-install 数据库迁移 hook。pre-install 早于普通数据库资源创建，post-install 在等待资源就绪后才执行可能与当前 API 的 schema 就绪条件互相等待。[Helm hook 生命周期](https://helm.sh/docs/topics/charts_hooks/)

```text
Secret + ConfigMap + PostgreSQL StatefulSet
                    │ 数据库可连接
                    ▼
            本 revision 的迁移 Job
                    │ Complete
                    ▼
 API initContainer 检查本 Job 成功 + 目标 schema
                    │
                    ▼
              API 主进程与就绪检查
                    ▲
Browser → Nginx ─────┘
```

迁移 Job 使用目标后端镜像：初始化容器只做有超时的数据库连接等待，主容器执行 `alembic upgrade head`。每次升级产生新的 Job，即使镜像 tag 相同也重新执行幂等迁移检查。Job 的 activeDeadlineSeconds 覆盖初始化等待，失败保留日志，不自动重建数据库。

API 初始化容器首先轮询本 revision Job 的 Complete/Failed 条件，再检查目标 Alembic head；不执行迁移。仅检查 schema 不够：如果 schema 本来已是 head，而本次迁移命令失败，API 仍不应绕过失败任务启动。因此 API 使用专用 ServiceAccount 和最小命名空间 Role，只允许 `get` 本 revision 的一个 Job；后端镜像新增启动等待工具，使用 Kubernetes 提供的 token/CA 访问 API，并设置连接、等待超时，不引入 kubectl 镜像。Pod 模板带 release revision 标记，确保每次升级都重新执行目标 Job 等待。

当前 revision 的 Job 在 release 存续期间保留，不设自动 TTL，保证将来 API Pod 重建仍能读取成功条件；升级由 Helm 删除不再需要的旧 Job，卸载删除当前普通 Job。发布等待工作负载和 Job 完成；任一超时或失败均报告失败并保留诊断。普通重试执行新的 upgrade 产生新 revision；同一 release 的发布操作串行执行。

### 4. Secret 创建、复用与保留

全新安装：确认没有同身份数据卷及旧 Secret 后，Chart 首次创建随机数据库密码，生成 `POSTGRES_PASSWORD` 和 `DATABASE_URL`，通过 Secret 注入，不把实际密码写入 values 或源码。数据库 URL 对生成值正确编码。数据库名和用户名在 ConfigMap 中配置。

升级与同身份重新安装：通过 `lookup` 读取同 namespace、同名称 Secret，复用原有数据字节；Secret 必要键缺失、与预期数据库配置不符或属于其他 release 时失败。旧部署接管直接复用 `database-secret` 的两个既有键，不计算新密码，也不把值打印到日志。若发现预期 PVC 存在而凭据不完整，在线渲染/预检必须失败，禁止随机补建凭据。

Chart 管理的 Secret 添加 `helm.sh/resource-policy: keep`，默认卸载保留；同名同 namespace 同模式 release 重新安装时复用并重新纳入管理。keep 资源可能脱离 release 的普通清理流程，所以必须在文档中明确残留资源及重新使用条件，并实测重新安装，不只依赖注解推断。[Helm 资源保留说明](https://helm.sh/docs/howto/charts_tips_and_tricks/)

在线安装需要能读取本命名空间 Secret/PVC 的操作者权限；缺权限明确报错。离线 `helm template` 无法验证已有数据与凭据关系，只用于渲染检查，不直接将其产物 apply 到已有环境。调试渲染可能包含 Secret 数据，文档说明不要将该输出提交仓库或作为普通验证日志。

### 5. 数据库卷生命周期

继续使用单副本 StatefulSet 的 `data` volumeClaimTemplates，默认保留 PVC；明确设置支持的 PVC Retain 策略，目标 Kubernetes 至少为 1.32，现有 kind 1.35 满足。PVC 由 StatefulSet 管理，不单独变成会被 Helm 卸载删除的普通 Chart 资源。重新创建同名 StatefulSet 时继续使用其对应的保留 PVC。[Kubernetes StatefulSet 卷保留机制](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)

legacy 接管保持 StatefulSet 名 `postgres`、serviceName、selector、卷模板名、存储请求和 PGDATA 等既有参数，不把它改造成另一种 existingClaim 挂载结构；避免触发不可变字段更新。额外 headless Service 等架构调整不纳入本次接管。

Chart 不管理 namespace 对象，安装时由 Helm 的 namespace 参数及创建选项处理；卸载不会删除命名空间。PVC 和 Secret 保留不代表删除 namespace 或 kind 集群后仍保留数据。恢复仍依赖集群外备份。

### 6. Nginx 同源配置

将生产 Nginx 配置改为 Chart ConfigMap，挂载到前端 Pod，代理目标由相同命名 helpers 生成的 API Service 得出。前端 Pod 加入配置 checksum，使代理配置变更触发更新。镜像自带配置可保留用于本地独立调试，但 Chart 部署总是注入对应 release 的配置。

保持静态文件与 SPA 路由回退，以及 `/api` 原路径转发；提供英文 NOTES，提示准确的前端 Service port-forward 命令。应用默认 Service 为 ClusterIP，本地入口继续绑定 127.0.0.1，无额外 Ingress 或登录功能变更。

### 7. 已有资源显式接管

不采用删除旧部署后重建，也不通过通用 force/take-ownership 选项跳过检查。新增显式迁移脚本或命令流程，指定现有 context、namespace、release 和 legacy values；默认执行检查，执行模式才修改资源。

流程先导出数据库到宿主机并验证备份非空、可读取备份目录；以资产 ID、内容和时间戳、PVC UID、Secret 内容散列作为基线，日志不显示凭据。记录受保护的旧资源配置和原归属元数据，作为失败恢复资料。

预检至少比较：目标 kind 上下文、旧资源名称和标签、StatefulSet 不可变字段、数据库名和用户名、PVC 绑定与容量、Secret 必要键及 URL 目标、目标资源现有 Helm 归属。任何冲突或缺失在修改前失败，不修改其他 release 或清空数据。

通过预检后，只给目标 Chart 管理的已有资源补充 `app.kubernetes.io/managed-by: Helm` 与 `meta.helm.sh/release-name`、`meta.helm.sh/release-namespace` 等归属元数据，再以 legacy 模式首次安装。动态 PVC 不强行作为普通 Chart 资源接管；旧迁移 Job 作为历史资源记录，验证成功后仅清理明确属于旧流程的完成任务，不套用批量删除。

接管验收必须检查 PVC UID 和 Secret 散列未变、数据库 schema/资产未丢失、Helm release 状态及真实 CRUD。首次接管不启用会自动卸载已有工作负载的失败清理选项。中途失败时保留数据并检查 release 状态，修复后重试；恢复旧工具管理需根据保存的元数据和匹配原配置单独执行，不自动卸载或重建数据库。

### 8. 验证与运维边界

静态验证使用 helm lint、默认/kind/legacy 三种配置的模板渲染与 Kubernetes 校验，增加非默认 release 名称和非法 values 场景。在线验证在隔离命名空间执行全新安装、数据库延迟、迁移失败、同 tag 升级、Pod 重建、卸载保留、缺失 Secret 拒绝重装、恢复正确 Secret 后重装、不同 release 的服务隔离；需要时构建仅用于失败验证的测试镜像，不提交实际凭据。

现有 `cap` 环境只进行已备份且通过预检的接管验证；破坏性失败场景在隔离的测试 release 上完成，不删除现有 `cap` 命名空间或 PVC。升级和重新安装后复用既有 Playwright CRUD 测试，验证英文界面与中文数据。

Helm 回退只管理应用资源，执行前检查 schema 兼容，不自动 Alembic downgrade。此 Chart 不新增业务 schema；以后有 schema 变更时，备份和兼容性评估仍是发布步骤。成功发布、失败排查及备份恢复说明使用中文，用户界面保持英文。

## Risks / Trade-offs

- [旧资源接管失败影响现有运行] → 集群外备份、不可变字段预检、归属快照、显式 legacy 模式、禁止自动清理数据库。
- [卸载后密码变化导致保留卷不可用] → Secret keep、在线复用、数据卷存在但 Secret 缺失时失败，并执行卸载重装实测。
- [迁移 Job 与就绪相互等待] → 普通 Job 与有界初始化等待，API 校验具体 Job 成功而非只看 schema。
- [为等待 Job 增加 Kubernetes API 依赖] → 最小只读 Role、有界轮询及清晰日志，不给 API 修改资源权限。
- [卷模板不能通过普通 upgrade 扩容] → 本次拒绝变更并说明需独立运维流程，不使用强制重建。
- [keep Secret 与 PVC 留下资源] → 文档说明保留和清理边界，重新安装必须使用同身份或独立数据迁移方案。
- [网络偶发失败、镜像未加载] → 先完成镜像准备，再开始发布；使用明确 tag 和现有 kind 镜像加载验证经验。

## Migration Plan

1. 实施时安装并锁定 Helm，开发 Chart、等待工具和文档，准备新的应用镜像。
2. 在现有 kind 的隔离命名空间完成默认及非默认 release 的全生命周期和失败场景验证。
3. 对当前 cap 部署执行集群外备份及只读预检，保存原配置和归属基线。
4. 显式以 legacy 模式接管；确认旧卷、凭据、schema、资产和 API 行为保持一致。
5. 更新默认部署入口，停用原始清单发布方式，记录安装、升级、保留数据的卸载重装与恢复步骤。
6. 更新 cap-002 验证记录和任务，执行严格 OpenSpec 校验。两项变更的归档另行执行，顺序先 cap-001 后 cap-002。

失败不触发自动数据库降级或数据销毁。上线回退仅在 schema 兼容时回退应用 release；接管前管理方式的恢复使用已保存的配置和归属资料，必要时按已验证备份方案恢复，不通过直接删除 PVC 解决发布错误。
