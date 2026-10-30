# ADR0044：受限WHERE标量值绑定（已接受，受限组件已验）

为现只读query加入$1..$16有界typed value，以一份v1 params_json文本供CLI及现MCP guradb_query，原JSON UTF8≤16KiB、类型int8/text/bool及typedNULL，密集恰用且不回显错误值。参数直接进入Rust AST表达式/typed DataFusion literal，不字符串拼接SQL，不动态标识符/PG prepared/session。精确上下文/输入与兼容以sql-parameters手册为准。

只在既有WHERE literal位置，LIKE保原非NULL固定%literal%规则。单一Rust parse/bind使direct/view/managed-view/Iceberg CLI及既有view MCP同语义；原无参API/源-view身份/SQL白名单及资源不扩。MCP params_json是字符串以保留原JSON的精确encoded-byte边界，外层RPC64KiB不扩，工具数/协议不变。

非作者先冻结SQLite真实bindings/literal差异、原行与类型/NULL/特殊字符/重复切值/错误恢复，官方SDK实发现调用及唯一新包fresh CLI+同prefix SDK闭合；只有限Q04首片，不授PG/全面SQL或安全认证。正常原B-H-M/源闭包与gate保持。Cargo合法gates明确locked/offline；仅必要执行器隔离适配，不跳过命令或修改质量阈值。

本包只继有09bc LinuxARM工具链、禁止依赖/镜像下载。尝试向旧docker build加network none会使rustup RUN层失配并请求离线bootstrap，实际明确失败已保；因此最小执行器改为inspect固定既存imageId、缺失拒绝，再network none/CARGO_NET_OFFLINE执行原cargo命令。不改命令/阈值或用作者命令替正常gate，非作者核真实argv与source绑定。当前仅本机预置工具链，完整首装/跨平台未宣称。
