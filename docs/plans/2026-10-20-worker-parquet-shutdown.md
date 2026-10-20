# 短生命周期 worker 的 Parquet 读取退出竞态

状态：进行中；task worker-parquet-shutdown，owner本CI修复任务，独占codex/fix-p0-native-builds worktree。follow-up基点4828d4a，完整PR原始基点302caa9，依赖PR1/2已合入；范围modules/query/worker.py、设计说明和本计划，无用户API/持久布局/锁文件/业务行为变化，无需修改用户手册。

实际证据：x86 Linux Python3.11.17诊断39367809537，固定源码4828d4a在原coverage顺序后累计235个测试时复现complete-workers shard1返回-6（SIGABRT），stderr为terminate called without an active exception，其他两片0退出。前一push39365535263同目标用例失败。ZIP SHA256 f9adf84970bd608a764f40ee79cff7b4d232db07ecafac6789eb39f88b179a8d，已归档共同Git目录guradb/worker-diagnostics/39367809537。

故障是原生退出而非超时/Python异常/覆盖比例不足。Arrow官方issue34314记录Parquet后台列读取在解释器退出时触发相同SIGABRT，use_threads=False为已报告规避；该issue不同版本，不能单凭它认定本仓库22.0.0的C++栈相同：https://github.com/apache/arrow/issues/34314 。本地锁定22.0.0签名已核对ParquetFile pre_buffer=False、read use_threads=True；官方接口说明use_threads控制列读取线程：https://arrow.apache.org/docs/22.0/python/generated/pyarrow.parquet.ParquetFile.html 。本次假设在短生命worker里同步列读取避免原生后台读取跨解释器退出窗口，须用同x86实际负载前后验证，未验证不能标已解决。

最小修复：仅worker中服务分片和export源文件两处Parquet读取指定use_threads=False。仍是三个独立真实worker并行，同一完整数据/列/真值/字节/内存、授权/版本、10秒deadline/取消及错误门槛；不降低recall、不缩小负载、不重试未知结果、不吞SIGABRT。同步解码可能影响多列性能，必须跑原functional/performance-smoke/stability-component，不能通过预算调整消除。

验收保留既有真实独立评分/全局归并/scan/export oracle和剩余source预算负例。诊断PR4将冻结修复后的精确提交，原coverage顺序和最多300次目标case/首次失败即停，比较旧235处abort与新退出结果；通过采样也不声称上游所有原生退出问题已解决。正常plan/check/hook、提交后check/task-finish以及完整原302caa9 PR范围check/checkpoint后，当前PR两版本与最终merge主线两版本均须通过。

恢复保留旧提交/checkpoint/失败产物，不强推或覆盖main。没有迁移/外部补偿，临时诊断不合入产品。独立复核须检查仅改变列读取调度、三进程/PID/记录数/错误与预算不变，性能证据未更换输入/缓存或阈值。
