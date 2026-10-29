# 单机 Rust SQL alpha（有界核心用例已通过非作者验收）

本次一次切换为可信操作者在单机运行的单进程CLI，不启动网络服务。
配置只指定一份本地Parquet文件及其预先计算的SHA-256；表名固定records。
文件仅支持Int64、Utf8和Boolean列，不读对象存储、外部目录或其它文件。

```sh
guradb query --config alpha.json --sql 'SELECT record_id, title FROM records WHERE active = true ORDER BY record_id LIMIT 10'
```

配置示例（路径相对配置文件；sha256必须替换为实际原文件摘要）：

```json
{"source":"records.parquet","sha256":"<64位小写SHA256>","timeout_ms":5000}
```

成功输出一个JSON对象，含源SHA256、列、完整结果行和是否截断。int64按十进制
字符串输出以保留精度。输入/SQL/执行失败只向stderr输出错误JSON且exit非0，stdout为空。
输出开始后遇管道关闭、超时或中断可能只写出部分JSON；消费者必须检查完整JSON及exit0。
SQL只支持单表列投影/别名、比较/AND/OR/NOT/NULL、列排序和LIMIT；
JOIN、函数、聚合、子查询、写入、参数、外部路径、HTTP/PG端口均暂不支持。
输入摘要不符、缺文件、损坏/不支持Parquet、执行期源变化明确失败。

资源作用域：每次调用一个进程，读取有界不可变bytes，Arrow批次及DataFusion
内存池只归本次调用；无后台worker、网络listener、持久目录、pin/lease或授权缓存。
默认/硬上界：源32MiB、解码64MiB、DataFusion池32MiB、输出2MiB、1000行，
SQL16KiB、配置16KiB、期限5秒（可设1–10000ms）。不允许磁盘溢写。
超时exit124，SIGINT exit130，进程退出回收本次所有线程、文件与内存；
成功/失败/取消后均可再次运行。输出在全部执行及源复核通过后才发布。
SHA256绑定的是原始Parquet文件bytes，不建立新的记录版本或目录发布协议。

旧Python在线索引、HTTP/PG、分布式worker、训练导出等demo已在真CLI跑通后实际删除，
本alpha不继续支持。历史设计/失败仍是历史，未来Rust能力见当前手册。
不得将此有界fixture通过宣称多租户、海量规模、兼容全域或可生产发布。

本次真实自测：独立四行Parquet核列投影、过滤、排序/LIMIT、源SHA256，坏摘要、
缺输入、损坏Parquet、函数SQL均拒绝，恢复原输入可重跑。真实进程测试验证输出
管道关闭、输出阻塞时超时/SIGINT及PID退出；16MiB源在打开期间改变时明确失败，
恢复原bytes再次成功。完整性能、长稳、覆盖率及发布未验证。
