# 当前 alpha 验证

当前真实产品只有Rust CLI；旧HTTP/PG/检索/worker测试随其能力退役，原断言与失败保留在Git和历史报告。
退役路径逐项列于[harness/alpha-retired.json](../harness/alpha-retired.json)，不宣称旧能力继续通过。

```sh
.venv/bin/python scripts/cargo.py build --package guradb --locked
.venv/bin/python scripts/cargo.py test --package guradb --locked
.venv/bin/python scripts/alpha_acceptance.py --run-dir artifacts/alpha/MY_RUN
```

固定Docker工具链无需安装本机Rust。直接运行CLI：

```sh
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config /workspace/artifacts/alpha/MY_RUN/good.json --sql 'SELECT * FROM records LIMIT 10'
```

Python仅用PyArrow生成已知行，字面expected独立核投影/过滤/排序/LIMIT、源SHA256、
损坏/缺输入/不支持SQL、变更拒绝和失败后可再运行。每个真实CLI容器退出后核已移除。
Rust integration tests在同一Linux容器内直接启动binary，留着真实stdout pipe不消费，
核deadline exit124、SIGINT exit130、关闭pipe exit1与实际PID终止；没有产品sleep钩。
这些用例证明当前进程作用域，不证明多租户、目录/PG、分布式资源平台或性能/长稳。

正常全项门禁用harness.py check（core/simple-alpha receipt）；产物在artifacts/harness。
工具协议toy测试单列于tests/harness，不能替代Rust/CLI黑盒结果。
