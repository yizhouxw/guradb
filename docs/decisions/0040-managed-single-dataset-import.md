# ADR0040：单机完整批导入与可恢复operation（本机受限候选已验）

沿ADR0036/0037，在新的显式store内扩展同一Rust catalog为managed格式，既有view捕获和读取语义不另造；旧v1/v2 root与directconfig不变，新root的dataset/schema/revision/operation提交事实由同一原子catalog权威给出。禁止Python在线数据库、第二套查询/目录权威或只给view起别名当托管。

单dataset/2revision/8operation/单inflight；完整输入先验证schema、Doc/asset与typed space，capturing admission持久化，owned捕获与目录同步后ready，catalog原子发布operation与revision/current。可公开status/reconcile/retry；partial失败显式清理，完整owned完成则继续，旧committed重放只返旧结果。parent current/generation复核防止当前范围恢复倒退，不宣传异步/分布式fence。数据128MiB含stage、描述1MiB/catalog16KiB和原执行预算保持。

schema为ordered(name,type,nullable)内容身份，只支持既有三标量；feature模式/space固定，记录source/feature/Doc/asset完整性。dataset identity生成一次持久化，revision绑定dataset/schema/generation/view。实际KILL与返回未知按公开恢复验收，不能以旧view故障矩阵替代。断电/恶意并发/共享授权/GC/演化/增量与完整M2均未授。

身份精确格式：dataset ID为首次admission用/dev/urandom读取32bytes后SHA256，持久不依赖path；schema ID为SHA256(`guradb-schema-v1`+LF+compact serde_json ordered Column数组，Column字段序name/kind/nullable，无尾LF)，kind固定Int64/Boolean/Utf8，最多32列。input指纹为SHA256(`guradb-import-v1` LF name LF sourceSHA LF featureSHA或none LF)；revision为SHA256(`guradb-revision-v1` LF datasetID LF schemaID LF generation十进制 LF viewID LF)。媒体/Doc声明由sourceSHA覆盖，owned bytes另逐一验；generation从1开始，feature模式与Space固定。

正式admission前预序列化capturing/ready/committed完整catalog（含新增view/revision/current），三态均需≤16KiB，超限不新增operation/捕获；不能已admit再因最终描述增长永久卡恢复。128MiB仍含暂存，未放宽。

实际候选验收采用独立原A15/B4/3media/typedSpace，3次真实STOP/KILL与public恢复、owned原源移除、旧op成功/失败不退和坏输入9类拒绝已过。V1派生count损坏误报是实际FAIL；V2 owned计数与committed完整Record/Space绑定定向修复，不改ID/格式/预算，不重KILL洗原失败。仅core-limited，精确H/M与新包仍走正常交付链。
