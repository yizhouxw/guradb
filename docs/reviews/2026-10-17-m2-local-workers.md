# M2 与本地三 worker 实现复核

范围：从 `dba9098927ecb96451b49266cb708886db529f90` 开始，隔离分支 `codex/complete-implementation`。
独立子代理均使用用户指定 GPT-6.1 Sol low；Graph/MCP、append验证、writer分别实施，交叉复核源提交/全局归并/门禁。

## 行为与真值

- Lance IVF_FLAT为显式可选派生索引；稳定键/revision，精确回表重排，过滤先于候选窗口，缺损拒绝，旧视图不被重建覆盖。
- Typed-edge一跳Graph与独立关系真值比较，方向/自环/int8/扇出/取消有负例；HTTP与三worker全局预算复核。
- Append触发验证完整parent chain、文件/字段/旧字节，重复operation对账，保留旧pin，当前执行仍是全量Snapshot/索引重建。
- 托管writer独立源意图/generation和单主机flock；真实进程退出覆盖before-source/after-source/after-confirm。PyIceberg独立reader核对事实，原custom reader验证托管源→ANN→refresh→HTTP训练闭环。
- 三真实进程承担不同记录分片，独立PID/实际行数/峰值RSS入报告；全局精确TopK/RRF、scan/Graph/训练与单节点真值相同。ANN与全局全文统计仍在协调器，完整M3未完成。
- MCP经公共HTTP transport，真实stdio子进程验证初始化、工具列表、describe、scan、status/results/cancel/release及非法token拒绝。未以注解替代服务端授权。

## 发现与处置

1. Lance native同步调用无法在执行中取消：改为有界子进程，deadline/cancel杀整个进程组并回收；真实慢worker测试确认PID已消失。
2. 未知源提交可能越过pending：严格对账，只有完整历史+HEAD==parent证明未提交才标aborted；其它情况阻断。已确认operation保存原metadata和摘要，后续append不改变幂等结果。
3. Writer单批有界但累计可能不可服务：增加总JSON、Arrow和Parquet字节上限，并测试跨批拒绝且源snapshot数量不变。
4. Worker依赖启动cwd：复现异目录native_failed，改为显式模块根；测试在临时目录执行真实Lance构建。
5. 新依赖NumPy2.5.4要求>=3.12：改2.3.5；实际本机3.14测试，下载并检查3.11 Linux NumPy/pylance wheel和Requires-Python，尚不冒充远端CI已运行。
6. 新driver增加最坏串行预算，初轮harness-tests检测7200<9000：仅调整CI总job上限到change150/release300分钟，保持所有原suite和单命令timeout、组件性能阈值，独立复核并自测。
7. 三worker内存及发布竞争证据不足：增加各进程峰值RSS和同视图训练遇新发布的真实测试；各峰值和不冒充同时总峰值。

## 实际验证与限制

首轮完整报告 `artifacts/harness/20261017T114002Z-60b12ad4/report.json` 为失败报告：除上述CI自测外8类门禁通过，已保留失败现场。
修复后局部CI/native tests及 `tests.functional.m2.run` 通过，后者包含托管append→ANN→refresh→三worker读/训练，以及并发新发布/MCP生命周期。
最终全量门禁在pre-commit和新commit上执行；对应commit、checkout指纹、原始范围、最终报告与checkpoint由task-finish receipt归档，不用旧报告替代。

固定性能8192行/16维/seed17仅组件smoke；两个查询向量的4/8探测测量不代表广泛ANN质量、冷对象存储或生产baseline。M2完整冷热/大于缓存、delta读取，M3索引分片/远端worker/spill/通用exchange，M4 HA/恢复/升级/长稳和分发SBOM仍未完成。

依赖实际package license文件/metadata：pylance Apache-2.0、Lance namespace Apache-2.0、NumPy组合BSD/MIT等；版本与文件SHA记录在artifacts/dependencies，并归档Git共同目录。完整传递原生组件许可与项目分发授权不在本轮生产验收范围。
无远端push/部署；代码回退不撤销已提交Iceberg数据。继续使用固定metadata/view和操作ID对账，保留目录/产物/pin后再考虑回退。
