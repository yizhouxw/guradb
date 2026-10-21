# 导入/同步本机 benchmark 合同（候选，未运行）

以下数值是**待owner实施前校准/冻结的本地POC目标**，不是实测、SLO或供应商比较；不自行承诺rows/s。先有正确性/失败无部分效果，再用真实实现计时；成本全量保留。它补足v1的PF，现有 Writer 每 op≤1000行/2MiB、累计表≤10000且追加前已有历史提交/文件<32，成功追加后累计最多32；新逻辑 job 的32输入批/10k为拟议工作流，不能冒称已有事务能力。SQL/CF1、质量、已有预算和最终G门槛保持。

## 固定公共输入与资源

- 固定seed `strategy-v2-poc-20261021`。业务正确性单独用P01全11可见事实/原ID-version与source-main+source-mirror；performance是另一个明确synthetic数据集，不能冒充P01/业务相关性。
- `perf-10000`恰好10000行：稳定ID按i编码；32个逻辑输入批次=31×312+328；这是未来单逻辑 job 的候选工作集，不是既有 Writer 的单 operation 上限。现有多 op 实验只能认证多 op 原语。3个业务字段int8/text/bool（含NULL）；id以i为基础，两个端点替换min/maxint8且保持唯一；title每11行NULL，否则固定Unicode前缀+zero-padded序号+SHA派生填充，UTF8≤256B；active每7行NULL否则i偶奇。元数据ID/version/source字段由同一已冻结适配映射显式加入，不借批序作业务ID。
- 4个固定不可变Parquet对象，每个2500行，PyArrow锁定writer；首正式源按已认证NONE/no-dictionary/DataPageV1/flat子集和field IDs写，物理 rowgroup/数据页依据所选真实 reader 的已认证格式限制固定；64 行/768KiB 是当前 P04 输出分页限制，不能冒充物理页/rowgroup 限制。不开未经认证 codec。全部objectVersion/size/SHA与规范行真值、文件总字节≤4MiB在首run前落input manifest并独审。若现adapter只支持旧3字段writer，就明确测该模块，不能伪造新Source schema/未发布QueryContext。
- 输入manifest≤256KiB；导入控制请求≤64KiB，仅引用固定对象，不在请求内塞完整rows。新导入Job/write budget必须由CF1-B owner先冻，不能拿A的已发布QueryContext替未发布ingest授信。reader/query仍受原≤30s binding TTL/原scope剩余时长约束，不逐attempt重置。
- 提议测量拓扑：单物理机、无其它测量，3个明确角色（真实PG控制面、真实对象后端、引擎/后台worker），每容器hard `--cpus=1 --memory=512m --memory-swap=512m --pids-limit=128`；总可分配上限3CPU/1536MiB。若worker在宿主仅能测RSS而不能硬限，就标该配置**不满足本 profile 硬隔离**，由owner提供受控容器后再计profile通过；不把RLIMIT_RSS当硬限。
- 引擎应用账本仍取已存在更小cap：输入encoded≤32MiB、decode≤64MiB、querypool≤32MiB、query输出≤2MiB/1000行、cache≤256KiB；新write临时文件总量提议≤64MiB并在创建前预留/累计，object source GET提议≤12（4个对象×至多3attempt）、所有remote requests≤128、接收bytes≤3×manifest总对象bytes+1MiB已冻结metadata余量。任何实际较小父预算优先。PG/object服务自身存储/WAL不冒充上述worker临时盘账，另测volume增量与WAL。
- CPU/RSS、scope费用、Docker memory peak、PG/object请求与字节、WAL/物化bytes、索引构建/预热、临时盘与cleanup均记；Docker磁盘卷没有已验证硬quota时明确只属测量，不声称全宿主磁盘隔离。

## BI-10K：固定版本导入→一个必需BM25就绪

每次新dataset/op、4源对象，单writer，索引仅固定中文预tokenized/BM25配置；不塞入未建模的vector/媒体负载。控制接受/持久op候选≤1s；事实commit候选≤30s；从接受到完整单BM25 view发布候选≤60s；单run绝对hard stop120s。rows/s、MiB/s从真实完整时段计算，不另许诺吞吐门槛。不得只计upload/heap或省略index成本。

first smoke做一次，用于验证profile能否执行/校准目标，绝不自比较。进入正式模块性能记录需5次独立fresh dataset/run且固定环境，每次均满足真值与绝对目标；报告max/median和完整样本，不用5个请求估p95/p99。cold=新引擎/无Gura数据cache，宿主/PG/S3 OS cache未清；warm=同固定版本重复读、write重放另列，不能把warm重放算导入吞吐。若走完整performance registry，遵守harness/evidence.md至少5独立运行/规定metrics；不把smoke塞进完整registry声称通过。

- BI-10K-R：同operation+全指纹重放3次，候选每次≤2s，事实行/view发布/索引逻辑产物增量为0；提交后丢响应一次，原op对账候选≤5s，不新ID盲写。
- BI-10K-N：分别注入单坏类型、batch间重复逻辑键、未知format feature/错摘要；候选拒绝≤5s，0部分发布。已确认事实若发生于后期失败必须如实data_committed=true，不伪称原子全撤。

## BS-APP / REPLACE / PIN / REC

固定V0=8192行（2物理源文件，每个4096），V1追加1808行（2文件，每个904），最终10000，ID不碰撞。V0/V1/native commit父链/旧文件不变/完整schema与checksum均先落manifest；reader 输出分页可更细，不能借此隐去累计总行数/文件数或扩大现有 caps。

- BS-APP：显式trigger接受候选≤1s；从trigger到V1完整单BM25 published候选≤30s、hard stop60s。3次通知+3次同op重放只产生一次逻辑发布；在原 TTL 仍有效的观察区间，V0 绑定在途 query 仍是 V0，新 query 为 V1；超过原 TTL 应拒绝，不能为跨越整个 ready 窗口续租或重置起点。所有source/commit/index/publish阶段及attempt累计计费。
- 查询干扰：固定5种既有只读谓词/排序/参数，分别在无append与append同时进行的匹配cold/warm窗口测真实结果/请求/字节/峰值和max/median；候选每次≤原10s，不承诺未经baseline支持的额外p95/QPS。更严相对回退阈值在有真实baseline后冻结。
- BS-REPLACE：同10000行完整受支持snapshot，用一个显式新 revision 删除一条既有逻辑 ID、修订另一条版本、加入一条新 ID，明确完整输入/预期集合仍为10000行；纯下架为9999行的功能负例另列，不拿它替代原性能工作集；替换published候选≤60s/hard120s。它验证正式完整snapshot重登记，不声称源delete文件或原地DML支持。非append update/delete/rewrite/schema输入须分类拒绝/显式受支持重建，不误推进append checkpoint。
- BS-PIN：用同版本两个query pin及一个训练pin的真实目录引用；已实现范围内精确撤权/GC拒绝候选≤1s，0仍引用对象删除。训练pin/源维护尚未实现时明确missing，此case不可用querypin替代报绿。
- BS-REC：在真实commit后丢返回、index前/后及publish前/后各一个固定断点，唯一op/manifest/receipt恢复对账；候选每次≤30s、0确认数据丢失/重复逻辑发布；未验证HA/PITR不宣称。本片无端到端实现时保持case pending。

## 校准与责任任务

`PERF-I0`由connectors/P11 primary：在生产实现前固定数据文件/摘要、输入batch/行大小、真实source adapter和write预算，核既有单 op1000/2MiB、累计表10k和历史提交/文件限制；新 logical job 的原子点、子操作与未知对账须另冻，不借分块取得跨提交原子性；`PERF-S0`由query/P11 primary：固定V0/V1/job/阶段时钟与故障点，catalog和index作为依赖；`PERF-E0`测试owner：独立真值、5次真实成本、环境/冷暖/失效证据。PM在tracked任务表具名；任何目标不合理须保留首证据、由独立review先修订profile再正式测，不因超时自动加预算或删工作集。

## 当前 reader 适用性与前置门槛

BI/BS 是完整导入/同步的后续目标，**不是当前 P04 fixed reader 的通过标准**：该 reader 仅认证总 1000 行、4 文件、16 rowgroup。10000 行 profile 对它当前为不适用/待能力认证，不允许按批规避累计限制。PERF-I0 必须明确选择真实可承接完整工作集的已有 legacy writer/reader（结果只归 legacy），或先独立验收新 reader 能力版本；沿用未升级的 P04 时必须拒绝。8192 行/两文件的原 M0/查询基线保持独立，不拿本 profile 的 4 文件或其它负载覆盖旧义务。上述 1s/30s/60s 是候选本地实验目标，未实测且未写入本轮产品门禁；正式冻结前由产品、模块 owner 与独立测试核对输入/能力/父预算，缺前提保持 pending。

| 当前组件 | 真实已认证边界 | 对 BI/BS 的准入结论 |
| --- | --- | --- |
| legacy Writer | 每 op≤1000行/2MiB；累计表≤10000，追加前已有历史提交/文件<32，成功追加后累计最多32 | 多 op 可独立测试；不证明单 logical job 10k 的原子/幂等合同 |
| P04 fixed reader | 总≤1000行/4文件/16rowgroup；输出页≤64行/768KiB | 当前不适用10k；不得用输出分页绕总量 |
| P05 sealed M1 | 源≤8192行/32批，结果≤1000行 | 不能承接V1=10000干扰查询；需要明确另一已认证消费路径或新能力 |
| P06 fixed index | 总≤100行/单shard/1MiB产物 | 不能承接单BM25 10k；全量索引能力须独立认证 |

PERF-I0 按整条 producer→consumer 闭包检查能力，不能只换 reader 后宣布 profile 可用。若走 legacy，各结果只归实际 legacy 路径；新固定链保持 pending。原作者稿中的容量与分页混同已由独立源码审查纠正，未改生产限额或既有负载。
