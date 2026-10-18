# PostgreSQL SQL 端口与客户端连接

状态：已实现有界本机切片，真实 psql 18/Psycopg 3.2.10 的 PG 功能、组件性能和组件故障子 driver 已本地通过；最终提交的整项 harness 证据以 task receipt 为准。下列是首片配置与合同，不能据此宣称全部 PostgreSQL 客户端、SDK 或 ORM 已兼容。设计见 [ADR 0014](../decisions/0014-bounded-pg-wire.md)，原始范围与最终证据见[变更计划](pg-wire-change-plan.md)。

GuraDB 的 PG 端口运行 M0 固定 Parquet manifest 上的只读 SQL；M1/M2 的 PostgreSQL 是内部控制面。连接控制面不会得到 GuraDB SQL 功能，也不应向客户端公开控制面凭据。

## 启用端口

沿用 [M0 构建与 fixture](m0-running.md)。在 `server.json` 增加可选字段：

```json
"pg_listen": "127.0.0.1:5433"
```

省略该字段不启动 PG 端口；`listen` 继续控制 HTTP。PG 首片只接受 loopback 地址，非 loopback 配置启动失败；不内建 TLS，客户端明确设置 `sslmode=disable`。数据库名固定为 `guradb`，用户名使用 `auth_file` 中的 `principal_id`，密码使用相同 principal 的原始 token。不能把 auth_file 中的 `token_sha256` 当作密码。

更新 `auth_file` 时，在同目录写完整临时文件并校验 JSON，再用原子 rename 替换；保持正确文件权限，不直接 truncate/覆盖服务正在读取的文件。服务会在执行和结果读取时重新读授权；读取到无效或不完整文件会 fail closed，PG 返回 `58000`，不能依赖旧权限继续访问。共享文件系统是否保证所用 rename 的原子性须按实际部署验证。

本地 fixture 的公开演示身份为 `reader` / `m0-local-example`。下面创建独立 PG 配置，不覆盖原有配置；执行目录为仓库根：

```sh
.venv/bin/python scripts/m0.py fixture --run-dir data/m0-pg
.venv/bin/python - <<'PY'
import json
from pathlib import Path
path = Path('data/m0-pg/server.json')
config = json.loads(path.read_text())
config['pg_listen'] = '127.0.0.1:5433'
Path('data/m0-pg/server-pg.json').write_text(json.dumps(config, indent=2))
PY
docker run --rm --name guradb-pg-demo \
  -v "$PWD:/workspace:ro" -p 127.0.0.1:8080:8080 \
  guradb-rust:1.90.0 /workspace/target/debug/guradb \
  --config /workspace/data/m0-pg/server-pg.json
```

PG 监听容器内部 loopback，普通 `docker -p` 不能将它转发到宿主。容器内客户端需要共享服务端网络命名空间，下面的 psql 示例采用此方式；原生运行服务时，客户端可直接连接同一主机的 `127.0.0.1:5433`。本片不提供跨主机连接或生产 TLS 接入。

## psql 与 SDK

另开终端运行 psql；`-X` 忽略可能发送额外会话 SQL 的个人启动文件，`-W` 交互输入上述演示 token：

```sh
docker run --rm -it --network container:guradb-pg-demo \
  postgres:18-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c \
  psql 'host=127.0.0.1 port=5433 dbname=guradb user=reader sslmode=disable' \
  -X -W -v ON_ERROR_STOP=1 \
  -c 'SELECT id, title FROM documents WHERE id > 2 ORDER BY id LIMIT 5'
```

SDK 必须运行在能访问服务 loopback 的同一主机或网络命名空间。以下构建仓库锁定的 Psycopg 3.2.10 客户端并与服务共享网络，示例 token 是公开演示值；自有数据使用环境注入的真实 token，不提交密码：

```sh
docker build -t guradb-pg-client:3.2.10 -f tools/m0/pg-client.Dockerfile .
GURADB_TOKEN=m0-local-example docker run --rm -i \
  --network container:guradb-pg-demo -e GURADB_TOKEN \
  guradb-pg-client:3.2.10 python - <<'PY'
import os
import psycopg

with psycopg.connect(
    host="127.0.0.1", port=5433, dbname="guradb", user="reader",
    password=os.environ["GURADB_TOKEN"], sslmode="disable", autocommit=True,
) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title FROM documents WHERE id > %s ORDER BY id LIMIT 5",
            (2,), prepare=True,
        )
        print(cur.fetchall())
PY
```

Psycopg 默认会自动开始事务，见[官方事务说明](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)。GuraDB 首片拒绝 `BEGIN/COMMIT/ROLLBACK`，必须启用 autocommit。Psycopg 的 `%s` 是驱动的值参数占位符，驱动会转换为 wire Bind 参数；不要自行字符串拼接。`prepare=True` 使用协议 prepared statement，不表示支持 SQL `PREPARE`。

## 首片兼容矩阵

| 项目 | 合同与验收范围 |
| --- | --- |
| 客户端 | psql 18、Psycopg 3.2.10；真实连接、查询、类型/参数及错误恢复已在本轮 PG 功能子 driver 验证 |
| 协议 | PostgreSQL 3.0、simple query、extended Parse/Bind/Describe/Execute/Sync/Flush/Close、取消 |
| SQL | 单表 SELECT、列投影、比较过滤、ORDER BY、LIMIT；继承 [M0 白名单](m0-parquet-http.md) |
| 值类型 | int8、text、bool、NULL；wire 类型编码保留完整 int8，Python 接收整数；text 不支持嵌入 NUL，参数或结果含 NUL 时明确报错 |
| prepared | 命名/未命名 statement 与 portal 有界；参数从列上下文推断，无法推断则报错 |
| 身份 | username 对应 principal_id，token 密码，固定 guradb database，查询执行重新授权 |
| 事务 | 只读 autocommit；业务事务、锁和写入明确拒绝 |
| 元数据与工具 | 无 pg_catalog/information_schema、SHOW/SET、`\d`/ORM/迁移探测兼容承诺 |
| TLS/跨机 | 未支持；仅受控 loopback，SSL require 连接失败 |
| 结果 | 复用固定 manifest 与资源预算；标准 PG 行结果不携带 HTTP read_context；超限报错，不静默截断 |

也不支持 COPY、DDL/DML、函数、常量 SELECT、JOIN、CTE、聚合、扩展 ABI 或检索 SQL。一个 simple query 只能含一个白名单语句，多语句不作为隐式事务执行。未支持类型/编码/启动设置及协议消息须明确失败；不能以 parser 可解析或连接成功代替该功能验收。

Startup 接受 user/database/application_name、UTF8/UTF-8 client_encoding 及空 options；不支持设置返回 `0A000`。较高协议 minor 协商回 3.0。输入 int2/int4/varchar OID 可按值归并到 M0 int8/text，但不新增可用 SQL 列类型。

每帧 64 KiB，SQL 16 KiB、参数 64、statement 32、portal 16、名称 128 字节；已认证连接最多 64，另留 8 个启动/取消容量。接收队列最多 8 条完整消息，超过即断开，不支持任意大的 pipeline。启动超时 10 秒、连接空闲 300 秒、每次结果发送总预算 10 秒；查询总超时继续采用 `limits.timeout_ms`。Execute 可分批返回有限结果，最多保留一个暂停结果；超过 `limits.retention_seconds`（默认 60 秒）的 portal 不可继续 Execute，Sync 清理 portal，prepared statement 保留到 Close/连接结束。

执行期取消/超时返回 `57014`，客户端可以等待同步后复用连接。结果发送途中取消、断连或超时会关闭连接，防止在半个结果包后追加错误消息；客户端应丢弃该连接与未完成结果。`server_version=18.0` 仅用于客户端协议兼容标记，附加 `guradb_version=0.1.0`；这不表示服务端具有完整 PostgreSQL 18 功能。

常见 SQLSTATE：`28P01` 认证、`3D000` 数据库、`42501` 权限/不可见资源、`0A000` 不支持、`22023` 参数、`42P18` 参数类型无法推断、`08P01` 协议、`53300` 连接容量、`54000` 资源上限、`57014` 取消/超时。客户端应按类型处理错误，不能自动重试不支持功能。

## 验证与排错

本轮 PG 功能子 driver 已通过 72 项断言，组件故障子 driver 记录 19 个事件，组件性能子 driver 完成 10 个样本。实际命令、原始报告、trace 摘要与限制见[独立复核记录](../reviews/2026-10-18-pg-wire.md)。这些是本地针对性结果，完整 M0/HTTP/PG 门禁和最终代码指纹以 harness/task receipt 为准；标准复现入口为：

```sh
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
.venv/bin/python scripts/m0.py functional
```

认证失败时检查原始 token 与 principal_id 是否匹配；数据库名必须是 `guradb`。遇到事务错误先确认 `autocommit=True`；遇到目录/会话设置错误应停用对应自动探测。SQL、资源、取消与参数错误返回 SQLSTATE；后续依据实现逐项扩展矩阵，不能靠忽略错误或关闭门禁获得兼容声明。

旧配置无需迁移。停用 PG 删除 `pg_listen` 并重启；若回退旧二进制，必须先删除该字段以满足旧配置的未知字段拒绝规则。该操作不改变 manifest 数据，不恢复已断开的连接或旧查询。
