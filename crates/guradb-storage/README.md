# Rust storage：固定对象请求计划

## M-S0 先行合同（Refs #122，待验证）

本片是纯内部结构验证，没有新用户路由、不执行对象读取，不改变旧
`Source::read`、Python 路径或持久格式。源码实现、独立复核、模块门禁及
真实消费者配对分别记账；当前不能标记固定对象读取已支持。

`fixed_request::plan_fixed_request(binding, reference, offset, length)` 接收由
common `cf1a/1.0` 严格解码的 `Contract`、`ObjectRef` 和字节范围，输出
私有字段的 `FixedRequest` 快照：binding 摘要、完整对象引用、offset、length。
计划只能由该入口构造；只读 accessor 不签发权限或证明 proof authority。

### 支持和拒绝白名单

按下列顺序失败，错误只含固定诊断，不回显对象 key 或请求内容：

| 顺序 | 输入/检查 | 预期 |
| --- | --- | --- |
| 1 | Contract 不是 read_binding | invalid_contract |
| 2 | common validate_range：引用形状/摘要格式/块表长度、非空不越界范围 | 保留 common invalid_contract |
| 2 | whole_sha256 不是整个对象、block_sha256 不完整块（尾块除外） | invalid_contract |
| 3 | 版本为 null 或 latest | unsupported_capability |
| 4 | 不在 binding 的 source metadata / revision objects / index shards 中 | unauthorized |
| 4 | 同 locator 但 size、sha256、integrity 任一字段不同 | unauthorized |
| 5 | 合法完整引用成员及范围 | 返回冻结请求计划 |

空版本/缺失字段/JSON null/错误摘要类型由 common 的严格形状检查拒绝；
未知契约版本或必需能力在 common decode 阶段拒绝，不另造协商或 fallback。
比较完整引用，不能只比较 backend/bucket/key/version；块表/proof_ref 的
相等仅证明与描述符一致，不证明其来源可信或对象字节正确。

### 资源、授权与兼容边界

只校验并复制 common 已有有限描述符，不分配对象 payload、不做网络、
缓存、GC 或重试。计划不检查当前授权、guard、时钟、取消和累计预算，
也不实现 ObjectReadPort。调用方不能凭计划读数据：后续真实 provider
必须接入同一权威 Control、重新授权、可信 proof 校验、字节校验及费用账。
rc2 的 ReadControl/受控接口尚未实现，不能在本模块复制。

旧 M0 语义保持，不迁移/切换旧生产路由；本片没有数据副作用。回退只需
停止使用新增内部 API；未来生产接线与旧路径退出需另行验收。

### 验证映射与当前证据

`tests/unit/fixed_request.rs` 维护字面 CF1-A fixture 和表驱动真值：三种
成员来源、whole/块对齐/短尾块，固定版本、边界/溢出、完整引用错配、
冻结快照及入站未知能力/版本拒绝。expected 不由被测 planner 产生。

先行合同记录时测试/编译/coverage/真实后端均 **NOT_RUN**。2026-10-25历史定向单测 D2 在当时固定源码与环境上运行7项通过；先前 D1 的临时目录不可执行失败保留。当前集成版本未重跑，完整 owner、coverage 和真实后端仍未验。阶段1仅允许编辑、plan
与限定格式检查；独审和真实配对待后续窗口。harness 的 storage 映射
是 legacy-m0，其通过不能证明新增 fixed-request provider 或 M/P ready。
完整 owner 分母包括 storage 的 Rust 与 Python 生产源；Rust 适用行100%、
Python80%，原21行排除不扩。lib.rs 的原两行排除 SHA 重绑由 E 独占处理。
