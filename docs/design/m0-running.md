# 运行 M0 读取服务

M0 是单进程、受控小文件读取 alpha。实际合同见[详细设计](m0-parquet-http.md)，测试入口见[验收映射](m0-validation.md)。仅支持 int8/text/bool、单表列投影/比较过滤/排序/LIMIT；JOIN、函数、CTE、事务、写入、索引、Iceberg 和分布式不属于此路径。PostgreSQL wire 在后续独立切片接入同一执行路径，当前状态、启用与 SDK 用法见 [PG SQL 端口](pg-wire-running.md)。

## 构建与本地示例

需要 Python 3.11+、Git、可用 Docker Engine；构建与验收会下载固定版本镜像和锁定依赖。本地及 Actions 使用同一个 Rust 1.90.0 构建容器，Cargo.lock 固定依赖。脚本通过 Docker argv 调用，不要求本机 Rust/Xcode。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock
.venv/bin/python scripts/cargo.py build --workspace --locked
.venv/bin/python scripts/m0.py fixture --run-dir data/m0
# 下面从项目根目录启动；127.0.0.1 是宿主唯一发布地址
# 示例 token 是公开的本地演示值，不用于共享环境。
docker run --rm --name guradb-demo \
  -v "$PWD:/workspace:ro" -p 127.0.0.1:8080:8080 \
  guradb-rust:1.90.0 /workspace/target/debug/guradb \
  --config /workspace/data/m0/server.json
```

另一终端提交、轮询、分页：

```sh
curl -s http://127.0.0.1:8080/v1/queries \
  -H 'Authorization: Bearer m0-local-example' \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT id, title FROM documents WHERE id > $1 ORDER BY id LIMIT 5","parameters":[2]}'
# 将响应中的 query_id 放入 URL，等待 status=succeeded
curl -s http://127.0.0.1:8080/v1/queries/QUERY_ID \
  -H 'Authorization: Bearer m0-local-example'
curl -s 'http://127.0.0.1:8080/v1/queries/QUERY_ID/results?page_size=2' \
  -H 'Authorization: Bearer m0-local-example'
# 后续页使用响应中的 next_cursor；DELETE 同一 query URL 请求取消。
```

句柄/result_kind/read_context/error/stats 与分页字段由 [OpenAPI](../../api/http/openapi.json) 定义。int8 返回十进制字符串，避免客户端丢精度。完整 int8 参数例：`{"type":"int8","value":"9223372036854775807"}`。句柄默认终态后保留60秒；重启清空旧查询、结果和游标，数据视图仍由同一 manifest 摘要固定。

## 自有受控数据

manifest 必须符合 [v1 schema](../../api/manifest/v1.schema.json)，每个文件记录真实长度及 SHA-256；列 schema 必须与 Parquet 的类型、顺序、nullable 完全一致。操作者在 server.json 固定 manifest 文件本身的 SHA-256，配置和清单在启动时读取，不接收 HTTP 路径/URL。更新清单需重启，产生新视图。

local root 使用容器内绝对路径，逐组件拒绝 symlink，只用于受信任开发数据。S3 backend 配置为 `kind=s3`、bucket、region、endpoint 与显式 allow_http；凭据来自 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / 可选 `AWS_SESSION_TOKEN`。文件可提供 version_id，服务按版本读取且仍校验完整摘要。M0 实测为 SeaweedFS 3.97，不推导所有 S3 服务兼容；唯一 retention_mode 是 best-effort，不保证长期历史保留。

auth_file 保存 principals 数组：token_sha256、tenant_id、principal_id、datasets（dataset UUID allowlist）。使用随机高熵 token，文件只保存 SHA-256；每次请求及排队任务开始执行时重新检查，错误时关闭访问。默认监听 loopback，容器示例才显式绑定0.0.0.0并仅发布宿主loopback。共享使用需受控网络和受保护代理；M0 不内建 TLS/OIDC，不作为不可信文件或恶意多租户的硬隔离沙箱。

资源参数只能降低硬上限：扫描32MiB、解码64MiB、引擎池32MiB、结果2MiB/1000行、运行并发2、句柄32、队列/执行总超时10秒、终态TTL60秒；不允许 spill。详情及其它输入上限见设计。每次查询完整读取并校验所有清单文件，尚无范围读取、谓词/分区裁剪或数据缓存。

## 验收命令

```sh
.venv/bin/python scripts/harness.py check
# 独立排错（同样真实启动服务，结束清理临时容器/网络）
.venv/bin/python scripts/m0.py functional
.venv/bin/python scripts/m0.py performance-smoke
.venv/bin/python scripts/m0.py stability-component
```

driver 只操作本次创建的合成对象、随机网络/容器与测试授权。证据在 artifacts/harness 的对应 run 目录（直接调用则在 artifacts/m0）。失败日志不覆盖；没有 Docker/镜像/依赖时失败，不 skip。完整 release 门禁仍因尚未实现的整库性能/故障/soak 明确失败。
