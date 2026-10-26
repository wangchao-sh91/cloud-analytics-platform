# CAP Helm Chart

一个 release 部署 React/Nginx、Python API、迁移 Job 和单副本 PostgreSQL 17。数据库始终随 Chart 部署。验证版本为 Helm v3.19.0 和 kind Kubernetes v1.35.8；Kubernetes 最低版本为 1.32。

完整流程见 [开发部署](../../docs/development-and-deployment.md) 与 [运维](../../docs/operations.md)。

```bash
helm upgrade --install lab ./charts/cap --kube-context kind-kind -n lab --create-namespace -f charts/cap/values-kind.yaml --wait --wait-for-jobs --timeout 10m
```

先完成镜像构建加载和在线预检。默认应用镜像为 cap-backend:cap002-v1、cap-frontend:cap002-v1；本地访问绑定 127.0.0.1。生产镜像地址与 tag 可由 values 覆盖。Chart 不增加公网入口或登录体系。

| values | 用途 |
|---|---|
| frontend.image / backend.image | repository、tag、pullPolicy |
| frontend.replicas / backend.replicas | 正整数，默认 1 |
| frontend.resources / backend.resources | requests 与 limits |
| database.image | 官方 PostgreSQL 17 镜像，拒绝其他大版本 |
| database.name / database.user | 首次安装时配置；后续保持稳定 |
| database.persistence | storageClass（空值使用默认类）、size（默认 2Gi） |
| database.resources | 数据库资源配额 |
| migration.waitSeconds | 每个启动等待阶段的超时，默认 180 秒 |
| migration.deadlineSeconds | 迁移 Job 总时限，含数据库等待，默认 300 秒 |
| migration.backoffLimit | Job 重试上限，默认 0 |
| naming.mode | release 默认隔离命名；legacy 仅用于显式旧部署接管 |

`values-kind.yaml` 用于本地 kind。`values-legacy.yaml` 只覆盖命名方式，必须经过接管预检，不能直接覆盖已有资源归属。名称过长时使用散列后缀保持隔离。

首次安装且无旧卷时生成随机 Secret；升级及同身份重新安装读取原 Secret，保持密码不变。有保留卷却缺少 Secret 时拒绝发布。离线 template 不会读取集群状态，不能用于绕过预检；其输出可能包含 Secret，不要提交或公开。

迁移采用普通 Job，每次 release revision 都重新执行。API 初始化容器只读查询本次 Job 完成状态，再检查 schema；它不执行数据库迁移。当前 Job 随 release 保留，不能通过 TTL 或手动删除提前清理。Role 仅授予读取本 Job 的权限。

默认 uninstall 删除工作负载与普通配置，保留 PVC 和 Secret。同 release、namespace、命名模式及数据库配置 install 可复用数据。不同身份是新的部署。不要用删除 namespace、PVC 或集群代替正常卸载。

存储类、卷模板容量、数据库用户名、数据库名与命名模式不支持普通升级变更；需独立运维方案。Helm rollback 只回退应用资源，不能代替数据库恢复或自动 downgrade。
