# physical-server-inventory Specification

## Purpose

为 Lab 的 Dell PowerEdge 物理机提供集中维护的资产台账，通过人工录入和查询统一管理设备标识、配置、位置、负责人及使用状态，并以英文界面支持日常维护。

## Requirements

### Requirement: 资产信息与唯一标识

系统 SHALL 为每台物理机生成稳定的内部 ID，并记录名称、Service Tag、型号、管理 IP、iDRAC 地址、实验室、机柜、U 位、CPU 摘要、内存摘要、磁盘摘要、负责人、用途、使用状态、备注及创建和更新时间。名称、Service Tag、型号为非空必填项，状态默认为 `available`；其他人工录入字段可空。Service Tag SHALL 去除首尾空白并以大写形式保存，且在数据库中唯一。名称和其他文本字段 SHALL 支持中文。

#### Scenario: 创建有效资产
- **WHEN** 用户提交必填字段齐全的资产信息，且未指定状态
- **THEN** 系统保存数据，生成 ID 和时间戳，状态为 `available`，并返回创建结果

#### Scenario: 拒绝重复标识
- **WHEN** 新增或编辑提交的 Service Tag 在规范化后与另一条记录相同
- **THEN** 系统拒绝保存，返回 HTTP 409 和英文错误信息，原有数据保持不变

### Requirement: 字段校验与使用状态

系统 SHALL 在服务端校验必填字段、可选 IP 地址格式和使用状态。状态仅允许 `available`、`in_use`、`maintenance`、`retired`，表示人工维护的使用情况。提供 U 位时 SHALL 为正整数；管理 IP 和 iDRAC 地址填写时 SHALL 为有效 IPv4 或 IPv6 地址。系统 SHALL 不采集设备状态或保存 iDRAC 凭据。

#### Scenario: 无效输入
- **WHEN** 提交空白必填项、无效 IP、非正整数 U 位或不支持的状态
- **THEN** 系统返回 HTTP 422 和可定位字段的英文错误信息，且不保存更改

### Requirement: 列表与组合查询

系统 SHALL 提供分页列表，支持关键词对名称、Service Tag、管理 IP 和 iDRAC 地址进行不区分大小写的子串匹配，并支持型号、使用状态精确筛选。关键词、筛选条件 SHALL 组合生效；响应 SHALL 包含当前页数据、总记录数、页码和每页数量。默认第一页、每页 20 条，页码至少为 1，每页数量为 1 到 100；默认按创建时间倒序、内部 ID 作次级排序以保证确定性。

#### Scenario: 组合筛选与分页
- **WHEN** 用户同时输入关键词、型号、状态并指定页码及每页数量
- **THEN** 系统返回同时满足所有条件的该页数据及过滤后的总记录数

#### Scenario: 无匹配或超出末页
- **WHEN** 查询无匹配资产或请求超过末页的页码
- **THEN** 系统返回空列表和准确总记录数，UI 展示英文空状态

#### Scenario: 无效分页参数
- **WHEN** 请求页码小于 1 或每页数量超出允许范围
- **THEN** 系统返回 HTTP 422 和英文错误信息

### Requirement: 详情与编辑

系统 SHALL 支持按内部 ID 查看完整资产详情和更新人工维护字段。更新 SHALL 保留 ID 与创建时间并刷新更新时间；不存在的 ID SHALL 返回 HTTP 404 和英文错误信息。

#### Scenario: 编辑资产
- **WHEN** 用户修改现有资产的负责人、用途或使用状态并保存
- **THEN** 详情与列表反映新值，且 ID 和创建时间不变

#### Scenario: 访问不存在的资产
- **WHEN** 请求查看或编辑不存在的资产 ID
- **THEN** 系统返回 HTTP 404，UI 显示英文提示

### Requirement: 删除与退役

UI SHALL 在删除前显示包含设备名称和 Service Tag 的英文确认提示；取消操作 SHALL 保留记录。确认后系统 SHALL 永久删除指定资产。退役 SHALL 通过设置状态为 `retired` 实现并保留资产可查询性。删除不存在的 ID SHALL 返回 HTTP 404。

#### Scenario: 确认删除
- **WHEN** 用户确认删除已存在的资产
- **THEN** 系统删除记录，后续列表不包含该记录且详情返回 HTTP 404

#### Scenario: 取消删除
- **WHEN** 用户取消删除确认
- **THEN** 系统不执行删除，资产保持不变

#### Scenario: 退役后查询
- **WHEN** 用户将设备状态设为 `retired`
- **THEN** 该设备仍可在列表和详情查看，并可使用退役状态筛选

### Requirement: 英文管理界面

系统 SHALL 提供资产列表、添加和编辑表单及详情视图。所有面向用户的 UI 文案，包括标题、标签、按钮、枚举显示、确认提示、加载、空状态和错误信息 SHALL 使用英文；用户输入内容 SHALL 原样保留其语言。状态显示为 `Available`、`In Use`、`Under Maintenance` 和 `Retired`。表单提交失败 SHALL 保留已输入内容并允许修正或重试。

#### Scenario: 英文界面与中文数据共存
- **WHEN** 用户在 `Add Server` 中输入中文名称、用途和备注后保存
- **THEN** 页面操作文案保持英文，列表和详情正确显示中文内容

#### Scenario: 请求失败
- **WHEN** 页面加载或表单提交遇到网络错误或服务不可用
- **THEN** UI 显示可理解的英文错误及重试入口，表单保留输入内容
