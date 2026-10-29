# ADR0029：固定真实图片caption的受限子串查询

2026-10-30，用户选择媒体内容/检索场景。当前仍为ADR0028可信单用户、一个本地Parquet、单Rust CLI；新增caption文本过滤，不引入模型/索引/服务。

仅开放text列 LIKE '%literal%'：case-sensitive、UTF8字面子串、1–128 bytes、内部%/_/反斜线拒绝，只有外层%作为边界。NOT LIKE/ILIKE/ANY/ESCAPE、非literal模式及其它SQL保持拒绝；由Rust编译白名单转DataFusion Expr运行，不由Python预计算命中。原16KiB SQL/内存/期限/输出及源一致性边界保持。

首例固定COCO image397133及5caption，离线准备单个200576B JPEG并用macOS ImageIO实际解码/核尺寸，Parquet只携带原caption及本地相对路径。查询进程不解码/识别图片；身份关联、caption和图片许可分别记录，不作全数据授权认证。只复制这一个有界用户产物，不扫描/下载/全包解压。

手册先行，独立原源truth、真实图片解码、换词/无命中与SQL拒绝、缺图/错误身份/失败清理同验。normal hook/PR及精确main core-limited继续；强化覆盖/性能/长稳/规模及发布未验，#138不在本片。
