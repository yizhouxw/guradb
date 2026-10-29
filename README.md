# GuraDB 单机 Rust alpha

当前alpha只支持可信单用户的一份本地固定Parquet源，通过一个Rust CLI进程执行有界只读SQL。
没有HTTP/PG监听器、Python在线服务、检索、训练或分布式worker。
详细支持/拒绝、输入SHA256和退出语义见[用户手册](docs/user/simple-alpha.md)。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python scripts/cargo.py build --package guradb --locked
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config /workspace/alpha.json --sql 'SELECT * FROM records LIMIT 10'
```

源码位于crates/guradb；固定工具链入口scripts/cargo.py。Python仅负责工程工具和独立fixture/黑盒验证。
完整Docker复现及自动化入口见[验证说明](tests/README.md)。

本轮一次退出旧demo，退役路径逐项登记[harness/alpha-retired.json](harness/alpha-retired.json)，历史源码可从Git恢复。
历史设计资料仍保留在docs，描述未来方向或当时合同，不能用作当前可用功能清单。
未来Rust检索数值缺陷#125、三模态规模#138均未在本轮解决。
架构取舍见[ADR0028](docs/decisions/0028-simple-rust-alpha.md)，普通hook/PR、非作者验收与精确main证据继续；Actions/部署保持暂停。
