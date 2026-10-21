# 变更计划：P00 CF1-A共同读合同

状态：本地module-only合同验收通过，PR CI与真实集成待验收；不新增数据库运行能力。基点169563cf4f0d36e7be8ad6600c941e0139126cf7，分支codex/p00-cf1a-contracts，独占worktree `/Users/chad/dev/guradb-p00-cf1a`。起始树干净；task p00-cf1a，checkpoint `checkpoints/20261020T232908Z-before-p00-cf1a-f544ac9c`。

## 验收与范围

依据[实施计划](../plans/2026-10-20-parallel-delivery.md)CF1-A和[合同](../interfaces/cf1a-contract.md)，冻结有界共同读所需身份/版本/授权/pin/预算/ObjectRef/ReadBatch/IndexArtifact，及登记发布CAS/fencing/幂等/未知结果。新增BindRequest、独立MutationAuth及IndexQuery/CandidateBatch，避免调用方伪造绑定或缺查询/副作用授权。Python/Rust真实双向round-trip、独立golden、严格正负例、每生产行100%覆盖且不加豁免。B/C及PG/S3/源提交/GC/现有服务接线不在本片，仍pending。

拥有 modules/common/cf1a*.py、crates/guradb-common/src/cf1a/与lib.rs模块导出、crate tests/example、api/cf1a/、tests/contracts/test_cf1a_contract.py、tests/unit/test_cf1a_*.py、docs/interfaces/cf1a-*、docs/design/cf1a-*、docs/user/{README,development}.md；不编辑其它owner范围。

## 风险与不变量

common不依赖上层、每源≤600行。固定版本不重取latest；索引覆盖/删除/模型缺口拒绝；AuthContext非凭据且访问须重新校验撤权；unknown结果先对账；完整预算/取消不省略；range whole hash不能冒充块校验。持久/运行行为无变化，无数据迁移和外部副作用。

## 步骤与恢复

先写本计划、合同、场景及用户页，保存实现前diff；再编写schema/golden和值/port、局部测试；独立复核；获独占窗口后完整check及覆盖率，提交后再check/checkpoint/task-finish。禁止并发性能测量。失败保留artifacts和diff；两次无新证据失败定位根因；通过原checkpoint在新目录恢复。

## 用户文档先行

用户手册与开发指南新增“待实现合同验证”说明；先行diff保存 artifacts/cf1a/docs-first.patch，该diff保存于行为实现之前。场景详见[验证映射](cf1a-scenarios.md)。合同验证不改变用户支持白名单。

## 验证合同

固定golden、int8上下界、NULL、非ASCII、递归重复/未知字段、bool/负数/溢出、缺预算/版本/能力、身份错配、保留不足、whole/block range、缺shard/源覆盖、CAS/fence/幂等/未知结果。真实跨语言命令编译Rust example并由Python来回交换；独立driver调用真实Rust进程与Python交换同golden。合同只做有界小输入，无运行时性能/故障声明；harness按plan选择的门禁仍实际执行，不能因此跳过。

## 结果与审查

本地修复后完整check的10项门禁全部通过：`artifacts/harness/20261021T003135Z-30b15493/report.json`，范围为原始169563cf到本任务全部变更，checkout digest为675ee4645ae927c51d0a98db922c0e22d6cac0b66c50f2e4abc056b3e595761b。Python生产行3365/3365、Rust原始3344行/覆盖3323行，沿用既有21行排除后适用3323/3323，无新增豁免。common独立LLVM覆盖1227/1227行；真实编译example后，独立driver双向交换12种golden并核对23种拒绝code。命令见合同；原始互通结果为`artifacts/cf1a/roundtrip-fixed.json`。最终提交、同步main后的原base报告、checkpoint与final-head互通共同Git归档由task receipt记录；PR CI与真实后端/I1仍待验收。

独立只读审查plan_audit完成最终源码及三行Clippy等价修复复核，无剩余阻断；18项Python单元与3项schema测试独立复跑通过。schema SHA-256=d24b63bbe618bc3aa123a5fa75310a9a21faeba0dfe1594e372827cca8d1c36e，golden SHA-256=0515723326834b6835c45424d9f216ebd900bec73eb11fdec287b1ba43971819。状态文档更新后仍执行hook和提交后原始范围完整check，不拼接旧报告。

独立复核已推动修正：typed NULL缺value不得由Serde补齐；JSON负零/UTF-8输入字节限额；共享generation首次发布与目标generation一致；opaque后端引用、squared_l2；源field变换/真实schema与资源schema分离；IndexRequirement含格式/配置/处理版本；MutationAuth和BindRequest；候选查询/分数/过滤/定位及delta计量义务。harness/coverage-exclusions未命中common lib，不修改任何豁免。

登记/发布实体缺口由独立ReadDescriptors+target_descriptors_sha256及三参数port关闭；正常/取消exact-lease release port已补。覆盖清单对纯模块/trait/type文件要求非空可执行映射，因此使用实际公共decode入口、ObjectRef物理身份方法与无状态port reauthorize/release helper；不引入cache策略或业务状态机，不新增豁免。

首轮完整precheck为9/10通过：artifacts/harness/20261021T001010Z-2bffa650/report.json；唯一失败是Clippy int_plus_one和large_enum_variant。修复仅把安全整数上界写为<2^53、两个大Payload variant用Box；JSON/schema/golden和语义不变。旧报告不拼入新结果，修后重新独立复核/编译/互通/覆盖与完整门禁。失败report/log/source.patch已保存到共同Git目录guradb/failures/p00-cf1a/88c41f8e4f3058f084b83767a08b6d0ed64704817c7d1a6bf1fb4ff32bdb5016。

下游预研待办：SourceReadPort的ReadBatch没有RowLocator，P06只能先做可信driver输入的module-only物理产物，P04→P06真实构建接线前须P00冻结located-build伴随定位port（CF1-B或兼容新增kind/cap）；不得猜batch行位置。IndexQuery.top_k为route窗口、candidate_limit为保留/输出候选容量、complete为搜索覆盖，已写明，不更改当前schema。
