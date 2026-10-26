# Helm 运维、接管与数据恢复

以下示例使用 `export HELM="$PWD/.tools/helm-v3.19.0"`。默认命名模式的 release `cap` 资源名前缀为 `cap-cap-`；已接管的旧部署为 legacy 模式，继续使用 `postgres`、`api`、`frontend`、`database-secret` 和 `data-postgres-0`。

## 接管已有 cap-001

只读检查：

```bash
python3 scripts/release.py adopt --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml -f charts/cap/values-legacy.yaml
```

执行接管前准备新后端镜像，保留原命名空间和数据库配置。明确传入执行参数：

```bash
python3 scripts/release.py adopt --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml -f charts/cap/values-legacy.yaml --execute
```

流程检查资源归属、选择器、StatefulSet 不可变字段、数据库身份、PGDATA、Bound PVC 和 Secret。随后将数据库备份到 `backups/adopt-<UTC时间>/database.dump` 并验证备份目录可读；保存资源快照及资产、PVC UID 和凭据散列基线；全部完成后才补充 Helm 归属元数据和发布 release。备份失败或归属冲突不修改工作负载。不会抢占另一个 release、删除旧 PVC 或重建数据库。

资源快照含 Secret，目录权限 0700、文件 0600，且 backups 已被 Git 排除。保护这些文件并按需另存到集群外位置。中途失败保留诊断和原数据；根据 `helm status` 与任务日志修复后重试，不自动 uninstall、删库或 downgrade。若需恢复原工具管理方式，根据资源快照恢复匹配配置及原归属元数据，单独评估，不直接强制替换 StatefulSet。

后续 legacy 升级仍使用两个 values：

```bash
bash scripts/deploy.sh --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml -f charts/cap/values-legacy.yaml
kubectl --context kind-kind -n cap port-forward --address 127.0.0.1 svc/frontend 8080:80
```

不要再应用 `infra/legacy-k8s/` 内的旧清单。旧迁移完成 Job 仅在确认其名称和原流程身份后单独清理，不批量删除其他任务。

## 升级与故障排查

发布前先构建和加载新镜像。每次 upgrade 产生新迁移 Job，即使 tag 不变；API 等待该 Job 成功及 schema 就绪后启动。

```bash
"$HELM" --kube-context kind-kind -n cap status cap
kubectl --context kind-kind -n cap get pods,jobs,pvc
kubectl --context kind-kind -n cap logs job/<迁移Job名称> -c migrate
kubectl --context kind-kind -n cap logs deployment/<API名称> -c wait-migration
```

数据库等待失败查看 Job 的 `wait-database` 初始化容器。当前迁移 Job 应保留，未来 API Pod 重建仍会查询它；不要手动删除。迁移失败不会自动回退数据。修复连接、镜像或迁移问题后重新 upgrade，产生新的 revision。

## 保留数据的卸载与重新安装

先停止 port-forward，再执行：

```bash
"$HELM" --kube-context kind-kind -n cap uninstall cap --wait --timeout 3m
kubectl --context kind-kind -n cap get pvc,secret
```

Chart 不管理 namespace 对象；默认卸载保留 PVC 与 Secret，其余本 release 工作负载、普通配置和 Job 被删除。重新安装必须使用相同 release、namespace、命名模式、数据库名、用户和存储配置：

```bash
# 已接管的旧环境保持 legacy 模式
bash scripts/deploy.sh --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml -f charts/cap/values-legacy.yaml
```

全新命名模式不要添加 legacy values。密码不会在升级或重新安装时轮换。已有卷但 Secret 缺失或不完整时流程拒绝安装；从受保护的原始凭据备份恢复正确 Secret 后再重试，不生成替代密码。更换 release 或 namespace 不会自动挂载旧数据。

## 集群外备份与恢复

以下以 legacy 的 `postgres-0` 为例，默认命名环境替换为 `<release>-cap-postgres-0`：

```bash
mkdir -p backups
kubectl --context kind-kind -n cap exec postgres-0 -- pg_dump -U cap -d cap -Fc > backups/cap.dump
```

确认命令成功、文件非空，必要时通过 pg_restore --list 检查归档。先恢复到独立空库验证：

```bash
kubectl --context kind-kind -n cap exec postgres-0 -- createdb -U cap cap_restore_check
kubectl --context kind-kind -n cap exec -i postgres-0 -- pg_restore -U cap -d cap_restore_check --no-owner --no-privileges --exit-on-error < backups/cap.dump
kubectl --context kind-kind -n cap exec postgres-0 -- psql -U cap -d cap_restore_check -c 'SELECT id, name, service_tag FROM physical_servers;'
```

确认全部字段和标识一致后，可单独清理临时恢复库。恢复到非空生产库需要独立方案；不要直接覆盖现有资产。恢复到全新安装的空台账，可在暂停 API 写入后使用有明确清理范围的恢复方案；迁移版本也需与目标镜像匹配。

## 回退及数据生命周期边界

应用 rollback 前备份并确认旧镜像兼容当前 schema。Helm rollback 不会撤销已执行的数据迁移，不自动执行 Alembic downgrade。初始迁移降至 base 会删除资产表，不能作为普通回退步骤。schema 不兼容时使用已验证备份恢复方案。

PVC 保留证明 Pod 重建和同身份重装可继续使用数据；删除 PVC、namespace 或 kind 集群可能销毁数据。保留卷也依赖原凭据。只有确实要销毁数据且已有经验证备份时才单独清理这些资源。
