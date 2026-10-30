# GuraDB 当前用户手册

唯一当前入口：[单机Rust SQL alpha](simple-alpha.md)。本轮为一次切换，不再维护旧Python服务或HTTP/PG demo。
当前可用结果以真实CLI黑盒与本次精确源码报告为准，完整产品尚未发布。
本地ASCII BM25、精确向量/融合、准确媒体与固定样本reader已有受限入口，见alpha手册；正式对象湖、Graph、规模和完整训练平台仍待实现。

- [本机预览安装物](local-preview.md)（本机有限验证）

[本地stdio MCP预览](local-mcp.md)已通过本机受限SDK验收，仅三只读view工具。

[M1单机出口教程与同源对照](m1-preview.md)已有本机受限候选验收，明确CLI/MCP白名单、既有输入及同源比较边界；完整产品未发布。

[单机托管完整批导入](managed-dataset.md)为单root/单dataset/两版本的本机受限候选，完整平台未交付。

[有界分组与基础聚合](group-aggregates.md)已通过本机受限语义验证，单group/完整输入最多200行；完整SQL/M2未支持。
