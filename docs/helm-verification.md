# cap-002 Helm 验证记录

验证日期：2026-10-23。工具：Helm v3.19.0+g3d8990f，kind Kubernetes v1.35.8，Docker 29.5.3，Python 3.12。Helm 从 get.helm.sh 下载并通过官方 SHA-256 校验，验证用可执行文件位于 `/tmp/cap-tools/helm`；仓库提供 `scripts/install-helm.sh` 供后续安装。

## 静态及工具验证

- 默认、kind、legacy values 的 Helm lint 与模板渲染通过。
- `HELM=/tmp/cap-tools/helm apps/backend/.venv/bin/pytest -q scripts/tests apps/backend/tests/test_wait.py`：26 passed。
- 测试覆盖：非法 values、PostgreSQL 大版本限制、release 长名称隔离、保留策略、不使用迁移 hook/TTL；等待 Job 成功、失败、404、权限错误、网络重试和超时；schema 已达 head 时也不能绕过失败 Job；接管归属冲突、不可变字段/存储/数据库身份/PGDATA/凭据校验、备份失败前不修改归属；连续 JSON 文档解析。
- `bash -n scripts/prepare-images.sh scripts/deploy.sh scripts/install-helm.sh` 通过。
- 后端新镜像 `cap-backend:cap002-v1` 构建并加载到 kind；前端未修改代码，已验证的同一前端镜像额外标记为 `cap-frontend:cap002-v1` 并加载。
- OpenSpec 严格校验及 diff 空白检查在交付前执行。

## 隔离全新安装与同源访问

在原有 kind 集群的 `cap-helm-test` 命名空间安装默认命名模式的 `lab` release；数据库、迁移 Job、API 和前端全部就绪。该命名空间为本次验收专用，原 `cap` 未用于破坏性失败测试。

```bash
HELM=/tmp/cap-tools/helm python3 scripts/release.py deploy --context kind-kind --namespace cap-helm-test --release lab -f charts/cap/values-kind.yaml
kubectl --context kind-kind -n cap-helm-test port-forward --address 127.0.0.1 svc/lab-cap-frontend 18080:80
```

在前端目录执行 `BASE_URL=http://127.0.0.1:18080 LD_LIBRARY_PATH=/tmp/cap-browser-libs/usr/lib/x86_64-linux-gnu npm test`，3 passed。浏览器通过真实 Nginx 同源入口完成英文 UI 和中文资产的添加、修改、搜索筛选、详情、取消删除、确认删除与不存在提示；另外两项覆盖请求失败和重试。临时 LD_LIBRARY_PATH 为当前主机缺少音频动态库的测试环境处理，不是应用部署依赖。

## 升级、Pod 重建、卸载及重新安装

1. 创建唯一测试资产，记录完整响应、凭据散列及 PVC UID。
2. 同镜像 tag 升级，revision 2 的迁移 Job 独立执行并成功；Secret 数据字节与资产全部字段保持一致。
3. 重建数据库和 API Pod，PVC UID `19d0d380-569a-4a9a-87f4-9feeb04399fd` 不变，资产 ID、时间戳、中文字段及凭据保持一致。
4. 尝试修改数据库用户名、数据库名、卷容量、存储类及命名模式，全部被预检或在线渲染拒绝，原资产未变化。
5. 默认 uninstall 后，普通工作负载、服务、迁移 Job、ConfigMap 和 RBAC 均被删除，原 PVC 与 Secret 保留。
6. 仅在隔离环境删除原 Secret，直接 Helm 重新安装被明确拒绝，未生成替代密码或替代卷。
7. 恢复受保护的原 Secret，再以相同 release、namespace、命名模式与配置安装，原 PVC UID、凭据及完整资产一致。
8. 为重装后的 release 建立 18081 本机入口，重新运行同样 3 项浏览器测试，结果 3 passed。

## 延迟、失败与隔离

- 使用仅针对测试 release 的 Helm post-renderer，为 `delay` 数据库增加 15 秒初始化等待；普通迁移 Job 和 API 等待依次完成，release deployed，没有死锁。
- 在已完成初始迁移的 `other` release 中，将下一 revision 的迁移命令临时替换为退出码 23；revision 2 发布失败，新 API Pod 未就绪，等待日志明确为 `Migration Job failed; inspect its logs before retrying the release`。
- 该失败发生时 schema 已达 head，证明 API 并未只凭 schema 版本绕过本次 Job 失败；资产整表 JSON 与凭据散列保持一致。
- 移除测试 post-renderer，revision 3 正常升级成功，资产和凭据仍一致，专用测试资产已删除。
- 同一命名空间同时安装 `lab` 和 `other`：API、前端与 PostgreSQL 服务选择器不同，PVC UID、密码不同；一个 release 的资产不会出现在另一个数据库。

故障注入只使用 `/tmp` 中专用 post-renderer，没有把人为失败命令或额外数据库延迟加入正式 Chart。

## 现有 cap-001 显式接管

先执行不带 `--execute` 的只读 adopt 检查通过，再创建一条专用中文测试资产，执行：

```bash
HELM=/tmp/cap-tools/helm python3 scripts/release.py adopt --context kind-kind --namespace cap --release cap -f charts/cap/values-kind.yaml -f charts/cap/values-legacy.yaml --execute
```

- 备份及资源快照位于 `backups/adopt-20261023094424/`：database.dump、resources.json、baseline.json。目录 0700，文件 0600，且不进入 Git。
- 备份生成并通过 `pg_restore --list` 验证后才修改资源归属。
- release `cap`，namespace `cap`，legacy 模式，revision 1，状态 deployed。
- 复用原 StatefulSet 与 PVC；PVC UID 始终为 `07705399-bc32-4f3a-a601-f118dc83b11e`。
- 原 Secret 数据散列一致，数据库整表 JSON 和专用资产 API 响应逐字段一致，包含 ID、时间戳和中文内容。
- 验证后仅删除该专用测试资产，并按明确名称及原镜像确认后删除旧流程已完成的 `migrate-cap001-20261023` Job。
- 新的普通迁移 Job 为 `migrate-1`，保留用于 API Pod 将来的初始化查询。
- 旧清单移动至 `infra/legacy-k8s/` 并标明只读迁移资料，原独立 apply 发布入口已停用。
- 接管后 8080 入口的浏览器验收：3 passed。应用继续使用英文 UI，支持中文资产内容。

## 结果与保留边界

验收使用现有 kind，没有重建集群，也没有删除现有 cap PVC 或命名空间。测试资产已按独立 ID 清理；接管备份保留在宿主机。测试环境中的卸载和缺失凭据实验不代表可以删除真实 namespace、PVC 或 kind 集群后无需备份恢复。

当前发布统一使用 Chart；部署时显式指定上下文、namespace、release 和命名模式。数据库/凭据保留的重新安装需要同一身份与兼容配置；Helm 应用回退不能替代数据库恢复。

最终清理：本次创建的 lab、other、delay releases 已卸载，随后删除专用 cap-helm-test 命名空间及其测试卷和 Secret；未删除原 cap 命名空间或数据卷。原 cap Helm release 保持 deployed，8080 本机入口可用，接管备份继续保留。
