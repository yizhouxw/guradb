# M1 单独复核记录

范围：原基点 `0e216895db06edf36dcdb91e540a80a3869d0bd9` 后的完整有界M1任务；实现后另行审查源码、差异、失败报告、资源与持久化边界。由同一作者进行单独轮次，未使用第二位审查者，非外部独立背书。

## 发现与修正

- Iceberg manifest遍历无稳定行顺序，不能拿writer的文件顺序作为样本身份。固定逻辑键编码/全量唯一性并在对外输出、训练导出时排序；PyIceberg/PyArrow独立真值按业务身份核对。
- 仅保存媒体URI不足以使训练pin保护依赖。改为复制所选metadata/manifest/Parquet/features/media闭包并绑定SHA，查询验证事实/索引/副本；导出媒体下载经过同一PG授权，源对象消失不偷偷切最新。
- M1早期扩展了公共ReadContext内部字段，违背已有封闭schema。现复用SourceVersion/IndexVersion形状，metadata作为独立源版本、分析器/模型进入opaque index_id；实时HTTP用M0公共ReadContext及M1 Job schema共同验证。
- 结果整数原生JSON number会丢失int64精度。M1 values/values_json改canonical十进制字符串，filter按字段类型核验，拒绝超出安全范围的JSON整数/非canonical字符串/错误布尔类型。
- generation/CAS分别约束构建次序与目录指针，ready不能提前发布。未知响应按operation/run对账；事务中断保留旧完整视图；新尝试失败也不能复活旧generation。
- pin统一owner字符串会使重启清理误删人工pin。改为manual/job/query独立scope；GC与新pin锁同一run，retiring阻止新pin；受控媒体/训练成功后继续保留job pin。临时query pin在取得独占服务lease后的恢复阶段清理。
- 排队时间必须计入deadline；提交时固定monotonic deadline，worker不能在等待后重新获得10秒预算。实际排队超过deadline、32槽上限、运行取消和执行期间撤权分别验证。
- PG重启会使旧session advisory lease失效，旧worker不能恢复终态。请求/结果发布检查旧连接，单实例锁失败关闭连接；恢复只把遗留任务标为失败，不重放。测试在旧worker阻塞时重启真实PG，接管后验证晚完成不能倒退终态。
- release先删DB记录再清文件可能在崩溃后留下不可追溯产物。现持有终态job锁及pin清理文件，再提交删除；中断保留目录记录/pin，可明确重试release。GC同样先标retiring再清目录，不碰外部湖。
- 数据集/run全局数量预算增加事务级锁，避免多数据集并发越过检查。各运行模块、Python依赖、entry/fixture和SQL配置均触发真实门禁；Python AST import DAG/compileall/pip check另行验证。
- 两次PG重启driver失败后保留日志并缩小诊断，发现Docker Desktop重启随机端口由49753变49771；不是数据库丢状态。driver重新发现本任务容器映射，再核对同一数据卷的指针/权限/epoch，不通过抬等待预算消除失败。

## 证据与限制

首轮整项 `harness.py check` 报告为 `artifacts/harness/20261017T103507Z-b724c945/report.json`，9类门禁实际通过，含M0回归与M1功能/性能/故障；复核后的最终提交需再次运行同样门禁，以task-finish归档为准。8192行固定组件负载、5次cold/warm、独立L2/RRF/训练、同负载后台重建/查询/训练并测均保留真实数据与成本；不拿首次绝对预算测量冒充历史性能比较或整库baseline。

M1生产实现为Python编排/PG控制与Tantivy Rust binding；M0SQL仍是原Rust/Arrow/DataFusion服务，没有宣称SQL检索融合、REST Catalog、schema/分区/删除文件全特性、多语言、ANN/Graph/增量/写入、HA/多节点或完整release。源构建后使用managed-copy，备份需PG与完整产物一致副本；代码回退不撤销目录/源保留状态。同步库调用不是任意CPU抢占、恶意文件/RSS硬隔离；只接受可信操作者源。

真实测量/trace/服务日志由M1driver按result SHA复制到共同Git管理目录的 `guradb/m1-evidence/`，harness命令日志/最终报告由task-finish另行归档；生成数据和构建物仍在artifacts，不提交。新代码未推送，远端Actions不能记为已验证；完整performance/stability/soak继续planned。

## 预提交阻断与非破坏性恢复

linked worktree第一次真实提交hook暴露旧harness缺陷：hook导出的GIT_DIR/GIT_COMMON_DIR/GIT_INDEX_FILE被suite子进程继承，临时Git自测误改任务分支、索引和共享仓库config。hook拒绝提交，原main仍为0e21689，所有M1源文件保留。失败worktree的artifacts/recovery保存source tar、config、index和reflog；恢复已知的作者、core.bare=false、.githooks配置，原任务abandon保留现场，再用harness recover从原checkpoint到/Users/chad/dev/guradb-m1-recovered新目录，启动m1-complete任务，未reset/clean/重写失败分支。

修复runner对所有suite清除Git声明的repository-local环境变量；临时Git测试自身也隔离环境。新增真实outer repo + linked worktree + nested git init/config/commit回归，核对父HEAD、index和config字节不变。最终真实pre-commit还需通过同一套自测，不能靠关闭hook提交。

新增依赖用途和固定版本见requirements-m1.lock/ADR0011。已核对安装分发包metadata/license：fastavro、Tantivy binding、SQLAlchemy为MIT，PyIceberg/PyArrow为Apache-2.0，psycopg/psycopg-binary为LGPLv3；原Rust Cargo.lock未改变。许可证文件SHA与用途归档在共同Git目录guradb/m1-evidence/dependencies-20261017.json；这是直接分发包核对，不能替代发布前全量transitive SBOM、原生附带库与分发许可审查。

最终边界复核补充：run持久保存published_epoch，验证“发布响应丢失→新版本发布→旧产物GC→旧operation重试”仍能返回原epoch且不倒退当前指针，不依赖旧产物仍可读取；未发布的旧generation仍拒绝。外部对象缺失转换为明确source_unavailable，真实S3删除测试核对具体错误而非接受任意异常。本任务的新PG schema尚未对外部署，published_epoch包含在首次schema v1；没有自动修改既有外部schema。

该补充的真实并发发布用例首先捕获锁前run读取的陈旧epoch；改为取得dataset锁后重新锁读run，再判断历史published_epoch。保留失败报告，未删除并发断言或改变预算。

输入复核要求metadata和features两者均为canonical SHA-256，显式null不能退化成无pin读取，负例验证不创建generation；独立M0兼容消费者的手工pin责任已明确。

最终导出边界负例：8MiB引号文本的二次JSON转义生成33,555,014字节manifest，原实现会给出随后无法读取的成功引用（artifacts/export-budget-probe保留复现）。导出前增加Arrow64MiB、Parquet32MiB、manifest32MiB减4KiB传输空间检查；同一大转义输入必须resource_limit失败，无部分成功，真实普通导出照常通过。
