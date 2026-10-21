# CF1-A用户文档场景与验证映射

状态：本地module-only合同验收通过，PR CI与真实集成待验收。此片只供开发者离线验证公共读合同，不提供用户服务入口。

| 字段 | 本次填写 |
| --- | --- |
| 场景/目标 | CF1A-READ：同一固定读绑定在Python/Rust逐值传递；CF1A-PUBLISH：发布请求不丢CAS/幂等/未知结果语义 |
| 手册 | [开发指南](../user/development.md)、[手册入口](../user/README.md) |
| 先行证据 | artifacts/cf1a/docs-first.patch；基点169563cf，先写文档再新增行为源码 |
| 支持/拒绝 | cf1a/1.0有界typed JSON、已保护固定源/无删除完整索引；未知字段/重复字段/版本/必需能力、缺预算、int8数值/NULL歧义、身份/范围/覆盖不一致拒绝 |
| 前置 | Python3.11+锁定requirements；固定Rust1.90容器；合成golden，无凭据或服务 |
| 成功 | 独立golden经Python→Rust→Python与Rust→Python→Rust保持值、规范字节/摘要；完整int8/NULL/非ASCII保持 |
| 失败 | 授权epoch/到期/保留不足，wrong dataset/view，partial whole hash，缺shard，CAS冲突/旧fence，不同幂等fingerprint；unknown写结果只能对账 |
| 预算 | 1MiB封包、1024行、64字段、TTL≤30s，全部预算必填；不证明执行器强制预算/取消 |
| 兼容/恢复 | 新合同与旧reader并存，无现有运行行为/迁移；未认证旧版本明确拒绝；没有外部写副作用 |
| 入口 | tests/contracts/test_cf1a_contract.py、tests/unit/test_cf1a_*.py、crate unit cf1a与example cf1a_roundtrip；完整harness按独占窗口执行 |
| 实测 | Python18项单元+3项schema、真实编译Rust与12种golden双向交换/23种拒绝code通过；修复后10项门禁全绿，Python3365/3365与Rust适用3323/3323行覆盖。报告`artifacts/harness/20261021T003135Z-30b15493/report.json`，最终commit绑定报告与互通归档见task receipt；不标运行时支持 |
| 复核 | plan_audit独立只读审查闭环身份/源映射、model/config/layout、范围完整性、授权/pin、mutation target/指纹/CAS与未知结果；PG/对象/I1/B/C仍缺且不属于本片实现 |
