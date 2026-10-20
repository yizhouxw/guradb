# P0 native ANN 构建启动开销修复

状态：已实现并通过本地九套门禁；提交后及远端验证待完成。任务 p0-native-builds，起点 main / 302caa9176bef6d29ef70bcf59c90ff4acbae1a6；独立 worktree fix-p0-native-builds、分支 codex/fix-p0-native-builds。原树干净，task-start 保存恢复点。

## 失败证据与验收

前一修复已经 PR #1 合入 main，PR 与主线 Python 3.11/3.14 CI 均通过。新分支首次 push 全树检查39348345677两版本均仅 performance-smoke 失败；3.14末次发布为63.027秒，超出原60秒窗口；8次更新共59.737秒。其他九套门禁通过。产物保留于前一工作树 artifacts/failed-ci/full-py314.zip；真实runner为2 CPU，不能把本地结果冒充其性能。

原实现每个快照构建全局和三个分片共四个独立Lance子进程。本地保持原60秒/256初始行/每批16行/8批/双并发查询/三worker测量，在 artifacts/p0-native-profile/native-times.json 记录每次真实 native 调用：每个约0.2秒，更新约1.2–1.4秒。此为定位证据，非受控产品baseline。候选优化仅消除同一次构建内重复的native初始化；必须仍构建全部四个索引，保持行/ID/版本、召回、预算与读写计量。

## 不变量与最小切片

关联 ADR0004/0007/0012，INV-001/002/003/004/007/008/009。拟将三个分片索引在同一个可取消子进程中顺序构建，全局索引保持独立；没有查询缓存或跨read view进程复用。每个索引仍是独立不可变Lance数据集、固定版本和逐文件摘要。聚合输入超出原MAX_BYTES时退回原单索引进程，不能缩小原可接受输入。每索引文件/字节、总deadline、取消与512MiB native RSS仍失败关闭。

范围白名单：native批量构建、分片调用与正负例；拒绝减少更新/并发/索引/读数、改变数据或定时偏移、放宽60秒窗口/latency/recall/RSS/门禁、通过暖查询缓存宣称提速。无API、存储格式或用户操作变化，因此不改变用户手册合同；构建进程生命周期和保守RSS计量需同步内部设计文档。

## 验证与恢复

先用独立exhaustive真值验证多个分片逻辑键、记录版本与重排/删除，验证独立路径、坏输入、取消和原输入预算回退；保留真实Lance及所有功能/组件性能/故障/覆盖率门禁。相同原始负载下记录前后native启动次数、构建时间、结果/recall及RSS；本机和远端2CPU分别描述，不能混为同环境回归比较。

实现后单独复核复杂度、输入放大、半发布、取消回收与证据，再提交后按原始base复验、task-finish与checkpoint；推送分支，PR远端检查通过后合入main并验证合并提交。失败保留日志与dirty现场，不盲目重复测量，不放宽阈值；回退使用revert新提交，不回滚源事实或改写历史。

## 本地结果与独立复核

`.venv/bin/python scripts/harness.py check` 报告 artifacts/harness/20261020T010850Z-c01de4a5/report.json 九套门禁通过。新增批量独立数据集/版本/精确真值、超输入上限回退、重复目录/部分结果拒绝、真实取消测试；Python全部163个unit/contract测试通过、2950个生产可执行行全覆盖，Rust原覆盖义务不变。

同机原60秒负载前后workload digest均为882e0df3a99901ca6cd651c677a588af9937e4cde4c3c9dd49ffefdb324273cb，dataset digest均为4423a6b2a160beb0d3bc800dc85e4b5fcaaab761c588634a54f97913cc1242f4；总native调用36→18，native总耗时7.50→3.95秒，8次更新1.20–1.39→0.77–0.99秒，最大native RSS约99MB（低于原512MiB）。保留前后raw trace、输入、响应、请求、生成索引与native-times.json：分别在fix-github-actions和fix-p0-native-builds两个worktree的artifacts/p0-native-profile。OS缓存未受控，这只是同机定位测量，不是产品baseline或远端性能证明；原完整performance/stability/soak仍planned。

单独差异复核：所有四个索引仍实际重建，分片逻辑键/版本及不可变格式不变；批次仅接受最多三个build，禁止混入query或递归批次；目录预检/结果数校验防止覆盖与zip静默漏项；输入聚合超限回退原单索引调用，共用原deadline/取消预算，任何异常仍沿construct原路径标记失败且不发布。共享进程峰值RSS在批内保守复用，内部设计已注明不能按独立进程相加。权限、源格式、训练和PG语义无改动；plan保守影响query/gateway，INV-010/011/012沿原功能套件验证。

新真值用例的初次查询恰落在ANN候选截断同距边界，改用非边界查询隔离批处理正确性；未删除或修改原有用例。首次Python覆盖率发现native正向batch仅在子进程执行而未被父进程coverage采集，补充直接native执行和独立数据集版本查询后全部生产行覆盖。失败现场与日志保留，不改阈值或豁免。

后续最终commit、提交后报告与checkpoint以task receipt为准；远端PR和合并主线必须按实际Actions结果继续验收。
