# ADR0030：图片结果使用投影整行DISTINCT

2026-10-30，继续ADR0028/0029单机单Parquet/Rust CLI，通过标准列投影SELECT DISTINCT返回唯一图片身份与本地定位。不是图片视觉去重、最佳caption选择或相关性排名。

仅支持既有列/别名/默认*投影及Int64/Utf8/Boolean/NULL。Rust在WHERE过滤后，先投影全部输出列、DataFusion distinct整行，再按已投影输出列名/别名排序并LIMIT。NULL tuple元素相等去重，文本case-sensitive。DISTINCT ON/表达式/隐藏输入列及位置排序拒绝，不忽略修饰符；非DISTINCT旧sort-before-select执行分支保持。

复用既有DataFusion32MiB内存池/no spill与源/解码/行字节/SQL/期限/取消退出上界，不加持久状态/额外预算，不先LIMIT后去重。无排序时不承诺结果行序。真实三图原caption投影集合、排序LIMIT与NULL/重复组合/别名和拒绝独验，normal hook/PR/精确main core继续；不重建媒体/模型平台或宣称完整兼容/发布性能。
