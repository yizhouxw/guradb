# ADR0036：单机本地固定视图完整刷新首片

状态：已接受并通过本首片有限验收；2026-10-30。沿ADR0028/0032/0031，可信单用户、Rust唯一权威、无服务/分布式目录。

view prepare捕获generic图文Parquet与SHA绑定JPEG到owned store；view ID=source SHA，request ID唯一映射content。最多2prepared/published记录，128MiB数据/1MiB描述、单源32MiB/decode64MiB/每media512KiB、每操作10s；source+3media每view上界约33.5MiB，不新增依赖。所有输入完整验证、own文件sync/目录sync才写prepared；publish原子catalog替换，catalog为current/已提交唯一权威，旧view不自动删。flock单writer读写排他，SIGKILL自动释放kernel锁，无lease平台。

pending先于staging，recover仅删除pending未被catalog引用的数据或清已对账journal；catalog中存在同request/content则不重复逻辑提交。相同request不同content、同content不同request、第三新view/未知格式/坏catalog/未ready读取拒绝，不自动修订事实或回退current。原输入是导入来源，捕获的owned bytes才是view事实；不控外部GC，备份保留caller负责。固定id query/search/media已迁移白名单，vector/hybrid/sample view拒绝；directconfig不追current。无特征复制，不能读旧features冒新ready。

功能独立真值为两真实caption集合V1三Doc与V2四Doc，原文/asset/bytes不造；旧新显式ID/current/search/media、同请求重试和错身份/缺失替换/版本/预算/未ready核。真实OS pipe填满后SIGKILL prepare进程（发布前）与publish进程（提交结果未知），以公开status/recover/retry对账，禁止内部JSON/rename恢复。未测断电、fsync故障、跨平台/恶意并发不授保证。

恢复与兼容：同v1公开recover/status处理pending；未知格式拒绝，旧binary不识新CLI；无原layout破坏迁移/删除。唯一实现源crates/guradb，Python只现有离线准备。高风险独审贡献集合外system-test，正常原B核心/PR/H-M/root全链。

首次bootstrap也在同一个不删除inode的flock内，初始catalog经临时文件原子写；公开recover仅重建已知空壳（.lock/空objects/有界catalog.tmp），不能在非空objects缺catalog时猜空库。真实bootstrap微步骤KILL/断电尚未测，known-layout夹具与静审不能冒完整故障认证。

实际有限验收：两原source成员版本、owned原文/字节、幂等/拒绝与三个真实KILL相位（prepared未publish、publish结果未知、pending/staging未入catalog）经公开恢复对账通过。完整M1.5/跨平台/断电故障仍未交付；工具失败原样保留。
