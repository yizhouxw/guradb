# GuraDB 单机 Rust alpha

当前alpha只支持可信单用户的一份本地固定Parquet源，通过一个Rust CLI进程执行有界只读SQL。
没有HTTP/PG监听器、Python在线服务、检索、训练或分布式worker。
详细支持/拒绝、输入SHA256和退出语义见[用户手册](docs/user/simple-alpha.md)。

以下命令在仓库根目录执行，需要Docker。已有.venv且已安装锁定依赖时，可从构建命令开始。
示例为4行合成数据，无需自行准备文件或填写SHA256。
`GURADB_FIRST_RUN_DIR`必须是仓库artifacts下尚不存在的相对目录；已有目录会明确拒绝，换一个新名字即可，不会覆盖。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python scripts/cargo.py build --package guradb --locked
GURADB_FIRST_RUN_DIR=artifacts/first-run
.venv/bin/python scripts/alpha_acceptance.py --run-dir "$GURADB_FIRST_RUN_DIR"
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config "/workspace/$GURADB_FIRST_RUN_DIR/good.json" --sql 'SELECT record_id, title, rank FROM records WHERE active = true ORDER BY rank ASC LIMIT 2'
```

既有fixture入口会同时做当前8项黑盒检查，成功打印`passed: true`，并留下`records.parquet`和
自动填写真实摘要的`good.json`。最后一条Rust命令exit0；JSON的`rows`必须严格为：

```json
[["r0", null, "0"], ["r1", "first", "1"]]
```

`columns`依次为record_id/text、title/text、rank/int8，`truncated`为false，
`source_sha256`等于good.json里的sha256；输入路径相对good.json解析。检查完整JSON和exit0才视为成功。


已持有COCO2017标注ZIP时，[真实32条元数据→Parquet→Rust结果](docs/user/simple-alpha.md#真实coco元数据入口)提供离线准备与确切5行断言；不下载或读取图像。

源码位于crates/guradb；固定工具链入口scripts/cargo.py。Python仅负责工程工具、离线数据准备和独立黑盒验证。
完整Docker复现及自动化入口见[验证说明](tests/README.md)。

本轮一次退出旧demo，退役路径逐项登记[harness/alpha-retired.json](harness/alpha-retired.json)，历史源码可从Git恢复。
历史设计资料仍保留在docs，描述未来方向或当时合同，不能用作当前可用功能清单。
实验索引实现已随旧demo退役，#125按not_planned关闭；原数值缺陷未修复，未来Rust检索不能继承正确性结论。
三模态规模#138仍是未来未验义务，本alpha不交付规模结果。
架构取舍见[ADR0028](docs/decisions/0028-simple-rust-alpha.md)，普通hook/PR、非作者验收与精确main证据继续；Actions/部署保持暂停。
