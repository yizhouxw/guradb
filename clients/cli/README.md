# CLI

状态：已实现M1/M2的Python HTTP薄适配，入口[m1.py](m1.py)，运行示例见[M1指南](../../docs/design/m1-running.md)。支持scan/search/export/graph、describe、status/cancel/release及JSON输出；查询参数原样转发公共HTTP合同。

连接由`--url`指定，token从`--token-env`（默认GURADB_TOKEN）读取。提交默认有界等待，`--no-wait`仅返回句柄；超时/KeyboardInterrupt请求取消，POST不自动重试。成功退出0，已处理的配置/HTTP/JSON错误退出1；服务端继续负责授权、固定视图和预算。

它不提供M0 SQL CLI、通用PG客户端、任意SQL/分页或公开写入。M0可使用[psql/Psycopg](../../docs/design/pg-wire-running.md)；训练选择、SDK/安装分发和完整互操作仍后续验收。单元边界见[测试说明](../../tests/README.md)，真实服务验收仍由M1/M2 driver完成。
