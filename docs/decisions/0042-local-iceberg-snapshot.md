# ADR0042：本地Iceberg v2固定快照的受限只读适配（已接受，受限实现）

以真实官方PyIceberg writer产生的metadata/Avro/field-ID Parquet验证Rust快照选择。原权威仍Iceberg事实链，不建立新catalog/托管写者；显式metadata版本与snapshot选择，不枚举latest。生产使用官方Apache Avro parser，metadata/路径/schema/live文件严格白名单，单live文件复用现共享SQL/预算，默认拒未实现delete/partition/evolution/多文件。PyIceberg仅独立工程writer与真值。

metadata.location作为逻辑file根与显式本地physical root映射，所有引用相对路径和完整readset哈希固定，query需显式预冻结readset pin，inspect不认证历史完整性。metadata单SHA不能替代子文件SHA。用户手册定义唯一readset算法与2MiB/2manifest/64entry/5文件双读上界，原执行资源不扩；字段ID以真实Parquet物理字段为准，不信ARROW:schema注释替代，LargeUtf8仅湖路径从物理UTF8恢复，不扩大原direct类型。

独立原A15/B4+官方writer metadata/snapshot/status事实先冻，跨current读取旧snapshot不漂移，错误URI/fieldID/缺文件/变更/codec/delete与预算同验。正常原B H-M/新Rust闭包/独审/cleanM新包fresh query/owner终态；只core-limited，未证分支保UNKNOWN，不靠手填正例。
