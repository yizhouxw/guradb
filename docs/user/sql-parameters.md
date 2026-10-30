# WHERE值参数（本机有限组件验收）

可信单用户、现受限只读SQL，用参数传标量值，不传SQL结构。CLI的query（direct config、固定view/managed view、受限Iceberg）原参数后可加一对`--params-json '<JSON文本>'`；其他命令不接参数。现MCP `guradb_query`增加可选字符串`params_json`，与CLI使用完全相同Rust输入解析/绑定；MCP仍只有三个工具、仅view query，不新增湖MCP。

输入JSON文本v1：`{"version":1,"values":[{"type":"int8","value":"-9223372036854775808"},{"type":"text","value":"a'; -- $1"},{"type":"bool","value":true}]}`。只允许version/values与每项type/value精确字段；version必须整数1；values为0..16项数组。type只int8/text/bool，任何type的value:null代表该类型NULL（type/value均必填），不接受untyped NULL。int8必须canonical十进制字符串、范围-9223372036854775808..9223372036854775807，不接受JSON数字/float/加号/前导零/-0；text为UTF8字符串（含空/引号/分号/注释形状/$文本仍纯值），bool仅JSON true/false。原JSON文本UTF8 encoded总≤16384 bytes，先核size再解析，未知字段/重复字段/版本/类型/范围或缺字段明确拒；错误不回显实际值。

SQL位置是`$1`至`$16`的精确十进制占位符，不接受$0/$01/$17/其他样式。引用需密集且输入恰好全用：$1重复可用同一值；仅$2但带两个值因$1未用拒；缺绑定/多余未用值/holes拒。无占位符无params保持原路径；显式version1空values仅在无占位符时允许，输出不加参数或新source字段。

只在原WHERE表达式允许scalar literal的位置绑定：现有比较的两侧、BOOL predicate/NOT/AND/OR、IS NULL/IS NOT NULL及原括号组合；原类型检查保持，typedNULL与列的类型仍须匹配，不做隐式cast。LIKE只允许原text列左侧/非NULL text参数作pattern，仍严格`%literal%`、keyword1..128 UTF8 bytes、无内部%/_/反斜线；不把参数化变成任意wildcard。`-$1`拒（负数放参数值）；projection/列名/表名/别名/LIMIT/ORDER/GROUP/函数名或aggregate参数等结构位置全部拒，未支持节点/运算继续拒。SQL字符串/comment内的$1只是原文本，不算引用；token/AST识别，绝不字符串替换/拼接值。

```sh
PARAMS='{"version":1,"values":[{"type":"int8","value":"1"}]}'
"$PREFIX/bin/guradb" --data-root "$USER_DATA" query --config /data/config.json --sql 'SELECT record_id,rank FROM records WHERE rank >= $1 ORDER BY rank' --params-json "$PARAMS"
```

```python
params = json.dumps({"version": 1, "values": [{"type": "text", "value": "%kitchen%"}]}, ensure_ascii=False)
reply = await session.call_tool("guradb_query", {"view": fixed_view_id, "sql": "SELECT doc_id,text FROM records WHERE text LIKE $1 ORDER BY doc_id", "params_json": params})
```

例子的source/schema/field由使用者既有受支持输入提供；参数更换只改变选择，原source SHA/readset/view身份保持，旧无参请求/结果JSON兼容。不把参数值当新源，不沿新源复用旧features。每次请求独立绑定，无持久prepared session/PG协议或跨调用残留。错误/缺多错型/未授权上下文/资源超限无成功payload，之后合法请求可恢复。含引号的字符串只比较真实值，不代表完整安全认证。

所有原SQL/AST、source32MiB/累计声明decode64MiB/retained Arrow64MiB/output2MiB/pool32MiB/no-spill、512MiB4CPU10s/aggregate全原始输入200（WHERE/LIMIT前）不变；有效值和LIMIT0不能隐藏坏源/坏完整view。CLI SQL16KiB/MCP SQL4096bytes、RPC行64KiB与session原预算不扩，16KiB参数记录还需同时满足RPC line（外层JSON转义计入原wire预算）。无新SQL算子/类型/标识符动态化/HTTP/PG/session/服务。新参数功能只随另名`guradb-parameters-preview-macos-arm64-docker-linux-arm64.pyz`及相邻.pyz.json发布，旧七包不冒支持；升级新prefix并存。已由独立SQLite原行与87 direct/view、4 lake/managed、官方SDK13同session实际验证；仅有限组件资格，正常H-M/新包交付独立记账，完整Q04/SQL/PG/发行未授。

已观察的旧lexer边界保留：`n>=-1`连写可被原PostgreSql tokenizer识别为custom operator而拒，使用已有合法字面式`n >= -1`或`n >= $1`传负值。参数化不放宽该旧语法，原拒绝与等价补证分别保留。
