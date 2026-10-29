# Simple Rust alpha 执行计划

基点25c281575368db9f76d2fda267ac6f59bbca5ec1；branch codex/simple-rust-alpha-20261029；
receipt ddc3044356314a43bb19ff34c62e6a36，先行合同docs/user/simple-alpha.md。
当前实现、有界自测、非作者验收、正常PR及精确main检查已完成，证据归本地目标卡；结论仅限当前alpha核心范围。无原始媒体删除、数据迁移或对外服务部署。

一个Rust crate复用既有SQL whitelist与Arrow/DataFusion：单源固定SHA256、
不可变bytes、有界解码/内存/输出；进程期限/中断终结作用域。
黑盒独立真值固定(record_id,title,active,rank)输入，核投影/过滤/排序/limit、
坏摘要/坏Parquet/不支持SQL、超时/SIGINT/可再运行及源执行期变化。
输出前输入/SQL/执行失败stdout为空；输出阶段失败可有partial JSON，完整JSON+exit0才可消费。
清理后无进程。先跑通这些真实结果再实际退役旧服务器。

退役范围：旧modules在线Python、m1/m2/worker与旧服务验收libs/客户端入口、
旧HTTP/PG/索引/集群等Rust crate及相关旧用例注册/运行docs/无用依赖。
保留通用harness、固定工具链与本用例的fixture准备/黑盒Python，按用途审查。
新alpha flow须覆盖全项删除和源闭包，不借用fixed-read flow；保留旧FAIL与历史义务。
通过适用门禁与非作者复核后正常提交，DRI负责PR/精确main与清理报告合流。

实际自测：唯一Rust crate的fmt/clippy、4单元及4真实CLI进程测试通过；独立Python
四行fixture的8个成功/失败/恢复黑盒案例通过；62个现行harness协议测试通过。
实际退役414路径，见harness/alpha-retired.json的分类/原因；其中254个.py，
modules/clients无剩余文件。保留Python只在scripts工程/fixture与tests/harness工具
协议测试；tests/fixtures/outline仅历史静态数据，不注册检索或训练能力。
原#125数值FAIL不改写、不复测为通过；检索未接当前CLI。

资源：输入bytes上限32MiB，解码64MiB，DataFusion池32MiB，无磁盘溢写；
stdout最多2MiB，1000行。主线程独立监督查询线程的读取/执行/源复核/回收/输出，
timeout/SIGINT用进程退出结束全部本地线程和FD，不创建外部资源或子worker。
范围是可信本地文件与有界fixture，不声称恶意Parquet解码的完整安全认证。
