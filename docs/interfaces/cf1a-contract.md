# CF1-A 共同读合同 v1.0

状态：本地module-only合同门禁与独立源码复核通过，PR CI与真实集成待验收；不新增运行时 API。唯一 owner：P00/common；catalog/source/index/query 的语义归属延续[概要模块合同](../design/outline-module-contracts.md)。CF1-B 接入生命周期、CF1-C 训练消费仍 pending。

## 边界与编码

版本封包 `contract_version="cf1a/1.0"`、`required_capabilities`、`payload` 全部必需。payload 是恰好一种有名值；所有对象拒绝未知字段、重复 JSON 字段、缺字段及错误类型。未知必需能力拒绝；空能力不能绕过每种值必需的能力基线。只认证1.0→1.0；不自动适配旧 M0/M1 描述符。

[机器 schema](../../api/cf1a/schema.json)与[golden](../../api/cf1a/golden.json)随实现冻结。摘要采用排序字段、UTF-8、不转义非ASCII、紧凑JSON的SHA-256；数值仅采用安全整数或规范字符串编码，不采用JSON浮点数。协议int8采用规范十进制字符串（含完整最小/最大值），SQL NULL是显式typed null；JSON number、bool冒充int、前导0、+号、-0与溢出拒绝。计数/epoch使用0到2^53−1的JSON整数，避免不同客户端静默舍入。

## 值与归属

- `ResourceDescriptor`：tenant/namespace/dataset/schema稳定ID、显示名、schema版本及有field ID的类型定义；v1.0只有record字段（int8/text/bool），完整资产/片段/特征/关系由B扩展，未知类型拒绝。
- `SourceVersion`：source/version稳定ID、manifest v1或Iceberg v2格式名和精确snapshot、metadata ObjectRef、field IDs、`protected_until_unix_ms`及原生保护证据引用。只有已冻结、已保护输入可登记；它不证明外部管理员永不删数据。
- `DataRevision`：dataset/schema、父revision IDs、不可变源版本集合、全部对象引用和内容摘要。版本集合不承诺跨源事务。
- `IndexArtifact`：固定revision/schema、构建/逻辑ID映射摘要、kind/模型/分析器/metric、覆盖源版本、删除语义与水位、全部分片及校验、构建成本和reader能力。A仅完整覆盖、无删除的固定输入；无分片、缺覆盖及模型错拒绝，不接受私有rowid作为对外ID。
- `ReadView`：固定revision、必需artifact IDs、发布generation/序、描述符摘要。只有catalog负责发布；索引不自行改变指针。
- `AuthContext`：tenant/subject/dataset、read操作、policy epoch、到期与可验证委派引用；不是bearer token且不含凭据。每次输出/句柄/分页须由catalog port重新校验当前epoch；pin不授予权限。
- `QueryContext`：request/query、tenant/dataset/schema、固定revision/view/source/index IDs、AuthContext、pin到期、deadline/剩余TTL、完整预算、取消域和trace/span；所有绑定身份必须一致，不允许worker补latest。TTL不能延长deadline；保留/pin/auth必须覆盖本次执行。
- `ObjectRef`：backend/bucket/key、精确version、大小、whole SHA-256与完整性模式。whole模式只认证整对象；block模式必须有可信块摘要引用、固定块宽与完整块摘要，强range校验仅允许覆盖整块（最后块可短）。ETag不充当SHA-256。
- `ReadBatch`：binding摘要、schema/field IDs、batch序与结束/截断/排序、稳定record ID/version、typed cells、计量及内容摘要；使用有界typed_json_v1等价编码，拒绝缺值/额外列/错类型和未支持Arrow IPC。后续真实Arrow适配需独立认证。

## 预算、取消和port

预算必填且正数：memory/object requests/object bytes/candidates/top-k/graph edges/output bytes/concurrency/temp bytes；A拒绝Graph执行，但预算不因算子未启用而省略。TTL上限30秒；batch最多1024行、64字段、1MiB封包。预算/取消字段不代表物理执行已受限；真实执行器须传递剩余额度、计入重试并支持取消。trace只使用不含SQL、URI或凭据的稳定ID。

common声明catalog bind/reauthorize/register/publish/reconcile/release_pin、固定object read、source batch read和artifact read的port；没有PG/S3实现、后台线程或业务状态机。

## 登记、发布与结果未知

RegisterIntent固定operation ID、请求指纹、tenant/dataset、预期目录generation、owner fencing epoch和revision摘要。PublishIntent同时固定预期旧view、预期generation、目标revision/view、单调publication sequence及artifact集合；不得在冲突后重读latest并重放旧build。请求指纹由规范payload摘要生成；同operation+相同指纹只能返回相同逻辑结果，不同指纹拒绝。CAS冲突与stale owner分别明确拒绝。

MutationReceipt区分applied/rejected/outcome_unknown，带operation/fingerprint和对账引用；outcome_unknown没有确定结果，禁止当作失败安全重写/取消无副作用。Catalog port必须先reconcile再决定后续操作。A只固定合同与确定性断言，不声称目录持久化、崩溃恢复、源提交fencing或GC实现；源写入/自动GC/B/C接口不在能力集内。

错误稳定类：invalid_contract/unsupported_version/unsupported_capability/unauthorized/revoked/expired_context/conflict/stale_generation/outcome_unknown/cancelled/deadline/resource_limit/corrupt_object/missing_object/backend_unavailable；只允许幂等读取在同deadline/预算内有限重试，未知写结果先对账。

## 兼容与验收

新合同并存于旧manifest/protocol；不修改旧运行行为、reader/writer、在途job/pin和数据。退回旧二进制时不能读取新合同；未接线使本片没有外部副作用。完整门禁后才可称module-only合同验证通过，真实PG/对象/源/索引及I1仍待后续包验收。场景与执行证据见[验收表](../design/cf1a-scenarios.md)。

## v1.0冻结细则与消费义务

本轮 JSON Schema 仅检查结构，**接收方还必须运行 semantic validator**；独立schema通过不证明int8边界、关联摘要、授权真实性、源保护或字节完整性。编码及错误优先级为：严格JSON/重复字段→封包字段→版本→能力类型/重复/未知→payload种类/必需能力→结构及语义。JSON计数token `-0`拒绝；输入和规范字节均不得超过1MiB（str先按UTF-8计字节）。所有ID键是固定ASCII，排序按ASCII键序；字符串采用UTF-8，双引号/反斜线及U+0000–001F按JSON转义，非ASCII保留原码点且不做Unicode归一化。

- Resource `schema_sha256`是完整fields数组摘要；Source分别携带上游真实 `source_schema_sha256`与目标 `resource_schema_sha256`。field mapping显式声明source field ID/source type、目标field ID/type与transform：`identity`要求相同类型；`key_v1`仅单一physical int8/text到逻辑text ID，必须使用现有类型化/长度前缀key v1编码；`revision_version`只允许派生record_version（source_field_id=0、source_type=none），值为固定DataRevision ID。P04必须核对真实源schema与物理字段、执行声明变换；不能把不存在的version列谎报成物理列。A不支持复合键或隐式类型转换；编码后ID仍受128字符上限约束，过长键拒绝。common不读取源行，映射声明不证明reader执行已通过。
- revision/view/batch摘要分别对该对象去掉自身 `content_sha256`/`descriptor_sha256`/`content_sha256`后的完整规范对象计算。意图request_sha256对完整intent payload计算，排除外层封包、独立MutationAuth和receipt；不把fingerprint本身放回输入。view的IndexRequirement绑定artifact ID、模型/版本/维数/metric/analyzer及format ID/version、configuration摘要和processing版本，模型错、配置错均拒绝。`squared_l2`明确为平方欧氏距离；不将其当普通L2。format ID/version为物理reader选择的必需描述符，fixture格式不表示真实索引已支持，实际适配器须明确认证layout与完整配置，未知reader/格式拒绝。
- ObjectRef的bucket/version为非空opaque值（≤1024字符、无控制字符/空白），不套逻辑ID语法；合法点号及`+/=`保留。metadata/源对象/索引shard出现相同backend/bucket/key/version时，size/hash/integrity须完全相同。block proof_ref由storage的可信authority验证，绑定backend/bucket/key/version/size和完整块表摘要；结构中有引用不授信，也不是外部调用方可自行签发的证明。
- BindRequest由认证入口提交单dataset、subject/委派引用、request/query ID、published或explicit selector、timeout/完整预算/取消域/trace。published请求的read_view_id必须为空，explicit为固定ID；只有catalog可在原子授权/pin事务中解析一次published，返回固定ReadBinding。不能用绑定输出充当绑定请求，不能在worker重取published。
- MutationAuth是独立值：tenant/subject/dataset、register/publish/reconcile动作、policy epoch/到期及委派引用。CatalogReadPort所有mutation/reconcile必须同时接收intent与当前授权，可信目录重新授权并校验fence；common只校验范围/epoch/期限关系，不认证委派真实性。授权不进入intent指纹，旧授权过期后对账仍须提供当前有效授权。
- 登记与发布共用目录generation；首次发布的旧view可为空且generation已因登记而大于0。只有generation=0时必须没有旧view。发布CAS必须匹配实际旧view/generation/owner epoch，目标view.publication_generation必须是expected_generation+1，publication_sequence严格大于真实旧序。Register applied回执精确指向target_revision_id；Publish applied精确指向target_view_id；两者generation均前进1。相同operation+指纹重放返回原逻辑结果，不重新递增；冲突不能改expected值后冒充同次重试。
- MutationReceipt applied必须有结果、无错误且generation>0；rejected无结果、带conflict/stale_generation/idempotency_conflict；outcome_unknown无确定结果、携带对账引用。对账只可返回同intent的确定applied/rejected或继续unknown；unknown期间禁止推断无副作用及另开相反操作。取消不声称撤销已应用写入。

### 精确索引请求与候选

IndexQuery由P05构造、P06消费，包含固定binding摘要、artifact/model/configuration/processing、kind/metric/analyzer、top-k/candidate-limit、query text或明确维数的有限向量，以及all或显式稳定ID白名单过滤。每字段必填；未冻结谓词语法拒绝。BM25要求非空text和空vector；exact_vector要求空text、squared_l2、none analyzer且维数匹配。向量与分数用16位小写hex编码IEEE754 binary64的大端bits，不使用未定义十进制字符串/JSON float；拒绝NaN/Infinity，向量分量绝对值≤1e150以保留距离计算边界，平方距离非负。

CandidateBatch绑定binding和IndexQuery摘要、artifact/metric、明确升降序、稳定record ID/version、SourceVersion/ObjectRef+row group/offset定位、完整覆盖标志与Usage。squared_l2升序、BM25降序，同分按逻辑ID字典序；不返回重复逻辑ID，不认证partial覆盖。消费者校验query/model/configuration/上下文一致、源/对象固定、过滤白名单、top-k/candidate及单批Usage预算。

locator是定位提示，不是身份。P04/P06必须证明对象属于声明的source snapshot，P10回表核对真实record ID/version；common的集合归属检查不替代这些真实断言。ReadBatch与CandidateBatch的Usage均为本批delta，协调者必须累计所有批次/重试/预取/清理并扣减父预算，单批校验不证明全查询总账或物理执行受限。上层负责及时传播取消与剩余TTL，所有输出重新授权。

### 可重现命令与状态

```sh
.venv/bin/python -m unittest discover -s tests/contracts -p 'test_cf1a_contract.py'
.venv/bin/python -m unittest discover -s tests/unit -p 'test_cf1a_*.py'
docker run --rm -e CARGO_BUILD_JOBS=1 -v "$PWD:/workspace" -w /workspace \
  -v guradb-cargo-registry:/usr/local/cargo/registry guradb-rust:1.90.0 \
  cargo build -p guradb-common --example cf1a_roundtrip --locked
.venv/bin/python tests/contracts/cf1a_roundtrip.py -- docker run --rm -i \
  -v "$PWD:/workspace" -w /workspace guradb-rust:1.90.0 target/debug/examples/cf1a_roundtrip
```

普通contracts套件不隐式启动Rust长编译；独立driver必须显式使用真实已编译Rust进程，缺工具失败。golden对两方向逐字节/逐值核对，拒绝语料同时核对稳定错误code；不以两端各自单测冒充互通。正式harness/独立复核及commit绑定报告仍是本片完成前提，真实I1生产子片保持pending。

### 未绑定描述符登记与pin释放

ReadDescriptors独立携带ResourceDescriptor/DataRevision/IndexArtifact集合/目标ReadView草稿，不含QueryContext、AuthContext或查询pin；它是登记/发布实体输入，草稿不代表published。CatalogReadPort.register/publish必须接收 `(intent, MutationAuth, ReadDescriptors)`，先验证实体、目标摘要及授权，再持久CAS；不能只收hash后要求调用方写内部表。两个intent都含 `target_descriptors_sha256`（完整ReadDescriptors payload的摘要），请求指纹包含它，防止同operation改resource显示名/namespace或索引shard却沿用旧指纹。已有revision/view摘要仍逐项核对。MutationAuth与target实体分别传递，授权续期不改变操作输入，target内容改变必须新操作与指纹。

ReadDescriptors验证资源/源/索引/视图关系；ReadBinding在同一验证上增加固定QueryContext/授权/pin/期限。A的多源输入必须使用相同逻辑ID与record_version转换策略，混合physical/derived version显式拒绝；因此batch的revision派生版本规则不会误施加给另一来源。Candidate的locator仍按声明来源由真实适配器和回表验证。

CatalogReadPort.release_pin接受以前签发的完整ReadBinding，完成、取消及失败清理均释放**相同pin_id与lease_id**；重复释放幂等，旧lease不能释放重新授予的lease。catalog验证认证owner或可信内部清理者，binding不是bearer token；即使读取授权过期/撤销，可信内部清理仍可释放该lease。响应未知不能宣布已释放，允许重放同lease或等待目录到期；pin续期/训练pin交接/GC不在A。reauthorize_read与release_bound_pin是无状态port检查辅助，不实现目录或缓存策略；ObjectRef.immutable_locator只返回固定物理身份元组。

已授权固定ObjectRef的404/NoSuchVersion归 `missing_object`（不可切latest）；429/503/暂时连接不可用归 `backend_unavailable`，只对幂等读在原deadline和剩余额度内有限重试，retryable可为true。其它A错误不允许自动重试；deadline耗尽报deadline。mutation网络失败无法确认未应用时仍须outcome_unknown回执，不能用backend_unavailable诱导盲重写。

### Route窗口与构建定位的后续准入

IndexQuery.top_k是**单条检索route返回窗口**，不是融合后最终全局K；QueryContext.budget.top_k是允许的单route/算子窗口容量，调用者必须为需要的route窗口预留足够容量。candidate_limit限制该route允许保留/传出的中间候选容量（top_k≤candidate_limit），不允许拿它截断必须检查的源记录或shard来换取速度。候选数、I/O、内存和deadline总账由P10协调者分配/合并，多route不能各自重置父额度。CandidateBatch.complete表示已按所声明固定源/全部分片完成搜索覆盖，不表示返回全部hit；返回窗口仍受top_k约束。无法完整搜索时失败，不将残缺窗口标complete。

当前SourceReadPort.read_batch只传记录/版本/值，不含RowLocator；不能从batch ordinal或数组行序推算物理位置。P06首个module-only切片可以消费独立driver提供的可信locator构建/读物理产物；**P04→P06真实构建配对前**，P00必须通过CF1-B或向后兼容的新kind/cap冻结located-build输入/伴随定位port，验证真实source snapshot中的object/rowgroup/offset及ID/version对应。此项保持pending，不在v1.0现有schema临时塞字段；P03固定对象读取port不受影响。
