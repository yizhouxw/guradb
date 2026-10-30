# ADR0041：共享Rust query的有界基础聚合（已接受，受限实现）

沿当前SQL白名单，由同Rust AST编译生成DataFusion aggregate plan，复用CLI/direct/view/MCP query，不引第二套Python SQL或服务。首片COUNT(*)/COUNT(column)，Int64/Utf8 MIN/MAX，optional一个raw group列；NULL与空集语义、输出dtype/alias、WHERE前与ORDER-LIMIT后在用户手册冻结。

聚合输入/组≤200、32MiB pool/no-spill与原源/输出/进程期限不扩；超限拒而非部分计数。默认group key排序，显式排序同分追加key，确保相同完整源结果确定。严格逐项拒绝不支持的函数修饰/表达式/分组节点，无忽略行为；原标量/DISTINCT路径保持。

功能真值先冻原A15/B4与独立NULL/重复/空集fixture；集合/已有独立SQL交叉核，实际CLI-view/标准SDK配对、旧view身份和拒绝/资源同验。正常hook/原B/H-M/core/独审/精确M新包/fresh消费者/owner清理；不授完整M2/PG/性能或发布。
