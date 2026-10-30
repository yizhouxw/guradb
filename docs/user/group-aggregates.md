# 有界分组与基础聚合（本机受限）

当前固定Parquet/确切view共享Rust query路径支持COUNT(*)、COUNT(单列)、MIN/MAX(单列)，以及零或一个显式列GROUP BY。COUNT列接受Int64/Utf8/Boolean，结果int8非NULL；MIN/MAX首片仅Int64/Utf8，忽NULL，结果同输入类型且可NULL。JSON仍沿int8十进制字符串、text字符串、bool与null，不改旧列元数据格式。

全局空输入或WHERE过滤后空：COUNT(*)/COUNT(col)为0、MIN/MAX为null；GROUP空输入无组。NULL key归同组，COUNT(col)忽NULL、重复行完整贡献；文本MIN/MAX及排序为当前Arrow/DataFusion UTF8字典序，不承诺locale/PG collation。WHERE先过滤，聚合完整输入后才ORDER/LIMIT。新聚合最多200input行/200group，超限resource_limit，不先LIMIT输入或截组计数；原32MiB pool、no-spill、source32/decode64/output2MiB、Rust512MiB4CPU/原期限不扩大，原标量query路径不变。

投影可为group列（可alias）或上述函数，非group列拒绝；无group仅函数。无alias函数默认输出名count/min/max，重名必须显式alias，重复输出名拒。聚合ORDER BY仅已投影输出名/alias，不接受位置或函数表达式；ASC默认NULLS LAST，DESC默认NULLS FIRST。无显式ORDER时group key ASC NULLS LAST；显式排序同分追加原group key ASC NULLS LAST作确定tie，LIMIT在此之后。group key可不投影，仍按其确定顺序。仅GROUP列投影可得到完整唯一组。

拒绝HAVING/window/ROLLUP/CUBE/GROUPING SETS、多列或表达式group、聚合FILTER/OVER/WITHIN GROUP/ORDER修饰符、函数DISTINCT/ALL、COUNT DISTINCT、嵌套/任意表达式参数、SUM/AVG、MIN/MAX Boolean、SELECT DISTINCT与聚合或group组合、JOIN/prepared/wire。未知语法/列/非法类型与组合全部unsupported，不能解析后忽略。原SELECT DISTINCT/标量过滤排序/NULL/LIMIT、检索/sample/managed身份恢复继续，不扩大HTTP/PG或MCP写工具。

目标示例：`SELECT image_id,COUNT(*) AS captions,MIN(doc_id) AS first_doc,MAX(doc_id) AS last_doc FROM records GROUP BY image_id ORDER BY image_id`；同view/query/MCP query得到相同完整结果。真实A15/B4新旧view统计独立核原行，nullable/重复/空输入用独立集合真值或已有SQLite交叉检查；旧view不追current。官方SDK将以新精确M安装物实际查询group，旧四包不覆盖，独立新包+sidecar，raw/模型不下载或运行。

本片已通过受限语义验收，仅受限Q09，不授SUM/AVG数值策略、完整SQL/PG/M2、性能长稳或发行。

## 现有输入的操作

先按[通用语料准备](simple-alpha.md)或当前COCO离线入口生成config/Parquet；本片不下载数据、不增加导入器。沿[预览安装](local-preview.md)取得本片匹配的精确M包（具名guradb-query-group-preview-macos-arm64-docker-linux-arm64.pyz，摘要与源码身份读取相邻同basename的.json发布清单）并安装到新prefix；旧四包不覆盖。PREFIX设为该安装目录，CORPUS设为已准备的config.json与records.parquet目录：

```sh
"$PREFIX/bin/guradb" --data-root "$CORPUS" query --config /data/config.json --sql 'SELECT COUNT(*) AS total FROM records'
"$PREFIX/bin/guradb" --data-root "$CORPUS" query --config /data/config.json --sql 'SELECT image_id,COUNT(*) AS captions,MIN(doc_id) AS first_doc,MAX(doc_id) AS last_doc FROM records GROUP BY image_id ORDER BY image_id LIMIT 2'
```

图文语料的image_id/int8、doc_id/text是现有准备入口的真实列；其他输入应使用自身schema中的raw列。A15完整输入第一条total为字符串15，第二条返回两组各5（LIMIT在完整分组后），source_sha256须与config一致、truncated=false；B4及任意自有语料按自身原始行独立核对，不能沿用A15预期。当前官方SDK的guradb_query使用同一sql/view，精确旧view统计保持旧源，不跟current；工具清单仍只有query/search/media三只读工具。
