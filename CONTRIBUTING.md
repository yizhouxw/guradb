# 参与当前单机 Rust alpha

先读[AGENTS](AGENTS.md)、[当前用户合同](docs/user/simple-alpha.md)和[harness](harness/README.md)。
生产入口只有crates/guradb，Python仅用于工程工具及独立fixture；不恢复旧HTTP/PG/Python在线demo。
用户可见变更先写合同，再实现真实结果/输入失败/可重跑/进程退出测试。

使用独占codex分支、worktree和task receipt，保留原始base。当前alpha采用core/simple-alpha，
正常hook、非作者复核、提交后精确检查和PR合入；不能跳hook或将toy工具测试称产品通过。
历史设计/用例可作来源，已退役路径见[harness/alpha-retired.json](harness/alpha-retired.json)。
未来覆盖、性能/长稳、release资格另验，Actions/部署保持暂停。
