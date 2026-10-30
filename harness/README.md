# 当前单机 Rust alpha 工程入口

依据[ADR0028](../docs/decisions/0028-simple-rust-alpha.md)，当前产品只有一个Rust CLI crate。
Python仅作为工程工具和独立fixture准备。旧HTTP/PG/Python服务、索引/worker等demo
已按[退役清单](alpha-retired.json)实际删除，旧操作不参与当前门禁。
历史质量/架构文档是当时合同或未来义务，不代表当前实现。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py task-start --label alpha-task --objective '单机Rust用例' --stage core --core-flow simple-alpha
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
```

已有active receipt可用task-stage绑定core/simple-alpha，原始base不变。
正常pre-commit自动沿用；需要clean提交索引且不跳hook。check固定候选、命令日志、
源闭包和工具指纹，错误/超时/缺driver或日志/运行中源码变化均拒绝通过。
本profile运行当前文档/能力与实际退役检查、owner/DAG/600行上限、全部现行harness
自测、工程Python编译、Rust fmt/clippy/test与真实CLI。Rust integration test真实spawn
产品进程，验证timeout/SIGINT/关闭输出pipe；Python只准备独立Parquet输入并核结果。

仅声明core-limited：不授予全域覆盖、性能/长稳、system或release资格。
原Rust适用100%/Python80%及发布义务保留待强化/发布；旧demo源分母不移植到新alpha。
`--stage hardening --scope release`仍因planned覆盖/性能/故障/长稳失败，不能把未测写PASS。

提交后按原base再check，用task-finish --report ... --review ...完成；checkpoint归档精确报告和日志。
无active receipt的合并后检查显式给`--base <合并前main> --stage core --core-flow simple-alpha`。
普通PR、非作者验收和精确main证据继续，Actions/部署保持暂停。

团队/调度唯一规范仍是[team-collaboration](team-collaboration.md)，本次不修改组织职责。

[资源记录与metadata基线](resource-records.md)为内部工程入口，已完成有限工程验收；不删除资源或证明历史峰值。

当前本机离线Rust执行器`scripts/cargo.py`只inspect并使用既有Linux ARM64工具链镜像`sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f`；不隐式docker build/pull或安装rustup组件。缺镜像/架构不符明确拒；运行network none/CARGO_NET_OFFLINE=true，既有locked/fmt/clippy/test命令与门禁不变。该机器前置不代表跨平台CI/首次工具链安装已支持，Dockerfile仅保留构建来源。
