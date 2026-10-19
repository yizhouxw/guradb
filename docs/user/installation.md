# 安装部署

这是当前源码alpha的SQL快速体验。它尚不能演示完整的图文数据接入、统一检索与训练旅程；单机产品预览/分布式发行要求见[生产准备](production.md)。

当前提供源码构建和本地受控 alpha 操作，尚无经验证的生产安装包、Kubernetes/HA 部署或滚动升级方案。下列命令从仓库根目录执行，使用合成数据；不要求配置真实湖或凭据。

## 环境与安装

需要 Python 3.11+、Git、可用 Docker Engine 和固定镜像/依赖的下载能力。Rust 使用仓库固定的 1.90.0 容器工具链，Cargo.lock 锁定依赖；无需本机 Rust/Xcode。M1/M2 的验收还使用固定 PostgreSQL 18 和 SeaweedFS 镜像，具体摘要由脚本锁定。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock -r requirements-m1.lock
.venv/bin/python -m pip check
.venv/bin/python scripts/cargo.py build --workspace --locked
.venv/bin/python scripts/m0.py fixture --run-dir data/user-quickstart
```

预期构建生成 `target/debug/guradb`；fixture 输出 `server.json` 路径，并在 `data/user-quickstart` 下生成 manifest、授权文件与合成 Parquet。目录专供本示例，勿指向已有业务目录。安装/构建失败先看[诊断](diagnostics.md)，不跳过依赖锁。

## 启动与查询

在第一个终端运行：

```sh
docker run --rm --name guradb-user-demo \
  -v "$PWD:/workspace:ro" -p 127.0.0.1:8080:8080 \
  guradb-rust:1.90.0 /workspace/target/debug/guradb \
  --config /workspace/data/user-quickstart/server.json
```

只将 HTTP 发布到宿主 loopback，容器只读挂载仓库；演示 token 是公开值，不能用于共享环境。在第二个终端提交：

```sh
curl --fail-with-body -sS http://127.0.0.1:8080/v1/queries \
  -H 'Authorization: Bearer m0-local-example' \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT id, title FROM documents WHERE id > $1 ORDER BY id LIMIT 5","parameters":[2]}'
```

响应返回 `query_id`。将下列 `QUERY_ID` 替换为响应值，先轮询状态直至 `succeeded`，再取结果；若终态为失败，检查返回的 error，不继续当成功读取：

```sh
curl --fail-with-body -sS http://127.0.0.1:8080/v1/queries/QUERY_ID \
  -H 'Authorization: Bearer m0-local-example'
curl --fail-with-body -sS 'http://127.0.0.1:8080/v1/queries/QUERY_ID/results?page_size=2' \
  -H 'Authorization: Bearer m0-local-example'
```

预期最多 5 行，id 大于 2 且升序；int8 值以十进制字符串返回。存在 `next_cursor` 时按[OpenAPI](../../api/http/openapi.json)取下一页；句柄默认终态 60 秒过期，重启后旧句柄无效。验证完成在服务终端按 Ctrl-C；`--rm` 清理本次容器，fixture 留在 data 下，勿批量清理其它任务资源。

## 选择其它部署路径

- PG 客户端：配置可选 `pg_listen`，按[PG 端口与 SDK](../design/pg-wire-running.md)使用 psql/Psycopg。仅容器内部 loopback，不能用普通端口映射暴露；客户端需同主机/网络命名空间，且启用 autocommit。
- M1/M2：需要预先准备内部 PG、真实 snapshot/metadata、特征摘要及私有产物根目录，按[M1 初始化](../design/m1-running.md)登记、构建、CAS 发布、授权后启动服务。示例 target 中的 URI/摘要是占位，不能原样宣称部署成功。
- 三 worker：先完成 M1/M2，再按[本地 worker](../design/m2-running.md)或[HTTP worker](../design/local-worker-http.md)启动。HTTP worker 使用三个不同端口和任务目录，仍仅限同机。

自有数据部署应记录 commit、依赖锁、配置摘要、源快照与产物目录，凭据仅通过受保护文件/环境注入。升级前冻结写入并备份；兼容与降级按[运维指南](operations.md)，不能只更换二进制后假定数据可读。
