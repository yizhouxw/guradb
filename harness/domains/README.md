# 按需加载的领域知识

领域由源码和合同定义，不是长期团队成员。成员在[五角色名册](../members/README.md)，技术实现统一由development按目标派短执行实例；common公共边界由architecture负责裁定，具体实现仍归目标包。

| 领域 | 必读入口（仅任务相关时） |
| --- | --- |
| catalog | [身份、授权、视图与发布](catalog.md) |
| storage | [对象、缓存与预算](storage.md) |
| connectors | [来源、格式与兼容](connectors.md) |
| query | [SQL、执行与融合](query.md) |
| index | [索引构建与检索质量](index.md) |
| cluster | [worker、取消与资源](cluster.md) |
| gateway | [协议、会话与客户端](gateway.md) |
| engineering | [共享工程与串行集成](engineering.md) |

这些入口引用已有模块AGENTS/设计/历史知识，不复制整个代码库或滚动任务状态。组织迁移不改机器源码owner、依赖DAG、产品能力和原质量门禁。无独立新事实时直接链接已有文档，不为每轮任务创建新知识摘要。
