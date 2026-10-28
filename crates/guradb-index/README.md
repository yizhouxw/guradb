> **Experimental internal library; not wired to production.** On 2026-10-28,
> a source-bound Python reference was evaluated for 24 fixed cases and the
> offline Rust test had 19 passing tests and one failure: case b05 differed
> by one binary64 bit (`3ff0d4da77d6a4d3` versus `3ff0d4da77d6a4d4`).
> Full-domain Python compatibility is not established. The checked-in gold
> remains NOT_COMPUTED; running the reference test requires an explicit
> freshly generated artifact and may fail on a real mismatch. This library
> does not replace the existing Python index or validate authorization,
> source protection, resource control, or production retrieval.

# M-X0 fixed scoring candidate

Refs #125; base `aae4a1a4c2f69bcf5d86187bbb777da2aa6b2678`.

## 先行内部合同：待实现、待验证

本片只增加内部 Rust 纯计算候选，不修改 Python 生产路由或用户行为。
Q 是唯一计划消费者；Q/A/T 尚未签收此私有 Rust API。它不是公共
CF1-A Candidate、locator 或新的源身份权威。Cargo、workspace、锁、selector
由 E 接线；本代码窗禁止编译、单测、coverage、数学 probe 和后端执行。
Rust 的 `pub` 仅供未发布内部库接线，不注册新的公共 wire 或客户端语义。

支持候选：

- `bm25-fixed-tokens/1`、`fixed-whitespace-v1`、
  `zh-CN-hand-segmented-v1`，k1=1.2、b=.75；固定分隔符、不归一化、
  保留重复查询词及原次序。全源统计先于过滤；NULL 文本计空且计入 N。
- `outline-synthetic-zh-image3/1`，三维 squared-L2、不归一化；显式
  present/NULL mask，NULL 原因非空；源和查询组件 finite、绝对值≤1e150。
- 调用者借入 expected/actual source-set 标识及完整 ID/version 集合，
  纯核只检查相等和闭包，不证明真实来源或授权。两来源合并语料仍总≤100行，
  不能逐源重算 BM25 后冒充全局统计；130 仅属独立 scan 分页。
- 私有库模型 `ScoredId` 保留 ID/version；BM25 降序、距离升序，同分按 ID，
  不截断、不融合、不回表。借入 checkpoint 可中止计算，不创建父 Control。

拒绝：重复 ID（含异版本）、缺行/额外行/错版本/错 source-set、超量输入、
无效模型/配置/词/维数/非有限值/超界组件、缺失显式 NULL 原因。
空语料或无匹配返回空；空查询词拒绝。未知过滤 ID 不产生伪造记录。
prepared 对象只能从完整行集合构建，不能注入不匹配的外部统计。

## 数值与验证限制

**HOLD-N1**：BM25 候选使用 Rust `ln_1p` 并保持当前 fixed Python 的逐词
运算/累加次序；尚未证明其与目标 Python `math.log1p` 逐 bit 兼容。
**HOLD-N2**：exact 候选按维度产生平方项，再用误差展开累加与末端舍入；
平方乘法与 Python `**2`、展开与 `math.fsum` 在全域的兼容尚未证明。
候选入口明确称 `score_candidate`。没有 epsilon 排序、默认兼容声明或生产替换。

独立测试设计包括字面词频/统计、NULL/空语料、过滤前后相同分值、重复查询词、
大小写/分隔符、完整身份负例、精确整数距离、同分排序、累加舍入边界与中止。
测试从 lib 的 cfg(test)/path 实际接入。独立 expected f64 hex/近同分全序、
两来源 full11 的真实配对、完整 owner Py80/Rust适用100、非作者复核和精确 main
证据均待后续窗口；fixture 不证明新 M/P 或 release。

不含 ANN、Graph、artifact 布局/I/O、发布/GC、认证/权限、全局选择/RRF。
无数据迁移或外部副作用；恢复只保留 worktree/receipt，不能据此停用旧 Python。

## 当前候选状态（非完成声明）

上述七文件的纯核/测试源码已经写入；所有测试均未编译、未执行。
advisory plan 实际选择 system，index registry 仍 pending。叶格式命令
`rustfmt` 返回 command not found；未探查/安装替代工具，格式验证仍缺失。
HOLD-N1/N2、E 构建/门禁、T 非作者复核及 Q/A 签收保持未完成。

## #168 先行测试强化合同（待实现、NOT_COMPUTED）

新独占任务只迁入上面七件冻结候选，新增测试参考源码与有限诊断材料；
生产 bm25/exact/score、既有两个 unit 文件保持原字节，不改 Python 路由、
Cargo 或共享接线。无新增用户行为；Q133 仅静态消费签收不变。

预先固定24例：exact x01..x12覆盖NULL、整数同分、相邻/半ULP、低位与维序、
subnormal平方、下溢、signed zero、符号差、大有限分量、过滤、平移小差；
BM25 b01..b12覆盖独立小语料、NULL全源统计、重复/混序query、近词频、
中文case/固定分隔、空域、合并11行、过滤、不匹配、反序同分。
每例完整ID/version和原输入先固定；24例不替代原full11物理配对或全域证明。

参考oracle只从SHA绑定的现有Python中提取完整materialize/score函数及实际
tokenizer/from_hex辅助函数，不调用Rust生成expected。运行时另外绑定实际Python
版本/平台、输入原bytes和oracle本身身份，生成分数16hex及完整排序。
未知gold保NOT_COMPUTED；对照测试不得ignore、容差比较或接受空gold。
若出现首差异，保case/两侧hex/身份顺序与原费用证据，不改公式令其过关。

本窗仅源码和AST/哈希/结构/plan静态检查。Python数值求值、Rust编译/测试/
coverage另申请模块窗；工具缺失不安装/改路由。有限24例即使零差异，也不能
解除全域N1/N2或退役Python。T独立核truth与delta；PM不代写gold。

### 固定case与truth映射

输入见 `tests/fixtures/diagnostic_cases.tsv`，字段分隔符为 `|`；V为原f64
大端16hex输入，N为显式NULL及原因；T为term=count游程，展开为原tokens列表。
这些是预先选定的输入bits，不是手填expected。`*`表示不加过滤。
每例保全部源行后才过滤；输入TSV的11行诊断不声称是原物理full11。

| cases | 诊断内容 |
| --- | --- |
| x01/x02 | 全零/显式NULL；整数距离及反序同分 |
| x03/x04 | 相邻ULP；两半ULP相加的舍入 |
| x05 | 大平方加两个低位，三种维度次序 |
| x06/x07 | 2^-537平方、2^-538及最小subnormal下溢 |
| x08/x09 | signed zero；混符号分量相减 |
| x10/x11/x12 | 2^498有限分量；完整域后过滤；平移后小差 |
| b01/b02 | 简单词项；重复TF、NULL计N及全源df |
| b03/b04 | 重复query词及混合次序逐项累加 |
| b05/b06 | 1023/1022近词频；中文/大小写/标点/固定分隔 |
| b07/b08 | 全空/NULL语料；空语料 |
| b09/b10 | 合并11行；过滤不重算全源统计 |
| b11/b12 | 无匹配；输入反序仍稳定ID排序 |

每例truth来自已绑定Python `materialize`/`score`完整AST节点，layout真实
SEPARATORS/tokens/validate_tokens/closed/from_hex也原样提取。测试shim只供
require/score形状检查及固定合法fixture，不声称代替完整公开admission。
参考侧按固定reader语义过滤/排序，不截断、RRF或调用Rust。
来源文件hash、完整输入/绑定文件原bytes、oracle源码hash和实际Python版本/
compiler/platform/math模块路径/float元数据写入运行产物。未锁定libm全域性质。

### 自持静态自检及后续申请命令

从仓库根执行；新树可借现有venv做标准库静态检查，不安装依赖：

```sh
.venv/bin/python -B tests/index_support/reference_oracle.py --root "$PWD" --check-source-only
```

该模式仅hash/AST，不compile/exec提取代码、不求值case、不写gold。
下面两步必须另获数值/模块资源窗，当前未执行：

```sh
.venv/bin/python -B tests/index_support/reference_oracle.py --root "$PWD" --evaluate --output artifacts/issue168/RUN/reference.tsv
GURADB_INDEX_REFERENCE_GOLD="$PWD/artifacts/issue168/RUN/reference.tsv" .venv/bin/python scripts/cargo.py test -p guradb-index --locked reference_bits_all_24_cases -- --nocapture
```

RUN为新独占运行目录，oracle以exclusive-create拒绝覆盖旧结果/模板。Rust要求
COMPUTED、三份输入身份metadata及9项实际runtime字段齐备，并按预列case顺序
逐行核ID/version/16hex；首差异输出位置和两侧bits，不自动改expected。
无环境变量时读NOT_COMPUTED模板并明确失败，不ignore/跳过/用空gold通过。
oracle辅助源码变更后须重算其`.sha256`并使旧gold失效，T核原件而非信任声明。

申请资源：Python单进程、24例/每例≤100行/行≤1024词，无网络/后端/模型；
提议30秒/128MiB上限（耗时/RSS待实测）。Rust诊断单进程，运行阶段提议60秒，
构建耗时/RSS未知；E先供合法BUILD-X包/共享工具/selector，PM另排构建与运行窗。
本测试只能报告这24例的差异；完整owner、数值全域、原配对/system/release另验。

### 本源码窗实际状态

24例输入、reference oracle、Rust bit/order断言及test-only lib接线已写出。
source-only命令实际exit0，核三份Python/三份Rust生产文件SHA和完整AST节点；
另做静态AST/24例闭合/原hex词法/行与词数上限/NOT_COMPUTED模板检查，未解码
浮点或求分数。静态自审加入求值前后source/input/oracle原bytes复核，运行时
若漂移则不发布COMPUTED产物。旧三份Rust评分与两个unit原件保持逐byte相同。
advisory plan为system、registry_not_connected，不冒模块门禁通过。
求值/格式/Rust编译及测试/coverage仍NOT_RUN，gold仍NOT_COMPUTED；候选交T
独核后再申请实际运行窗。没有提交、推送、PR或完成checkpoint。
