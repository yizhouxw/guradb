# 分发与依赖清单

当前用户仅授权本地开发/提交。未作项目许可证选择，不对外发布包、镜像或授予开源许可。

生成本机实际安装Python依赖及Cargo锁定依赖的机器清单：

```sh
mkdir -p artifacts/dependency-review
# 使用已按README构建的固定Rust镜像；输出目录每次选新名字。
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -v guradb-cargo-registry:/usr/local/cargo/registry guradb-rust:1.90.0 \
  cargo metadata --format-version 1 --locked --offline > artifacts/dependency-review/cargo-metadata.json
.venv/bin/python scripts/sbom.py \
  --cargo-metadata artifacts/dependency-review/cargo-metadata.json \
  --output artifacts/dependency-review/sbom.json
```

清单使用 `guradb-component-inventory-v1` 自有JSON格式，列purl、精确版本、Cargo锁checksum、依赖锁摘要及本地包声明的许可。它不是SPDX/CycloneDX兼容性认证，不把缺失许可当作许可通过。Python清单包括开发工具，不声称是最小运行时依赖集。

`--require-distribution-approved` 当前明确失败。分发前需要权利人确定项目许可、审查每个实际打包依赖及NOTICE/许可文本、生成最终镜像OS包清单、明确codec/词典/模型资产许可和升级/兼容政策。仅本机依赖元数据不证明这些义务完成；不得用猜测的许可填补空白。
