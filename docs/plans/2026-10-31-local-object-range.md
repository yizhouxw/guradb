# 变更计划：固定本机HTTP对象有界Range

状态：先行合同/必要设计审查完成，新增待实现。B6bcf655cabfa9c9266d61f3329a4b2b7ebc4376a；codex/local-object-range树/Users/chad/dev/guradb-local-object-range；receipt c185fcd50e2442779465541ab653b8c3/checkpoint checkpoints/20261031T002940Z-before-local-object-range-b7b05d7f。初始clean/onlyRoot，PM六规划MD不改。

用户页local-object-range/ADR0047先于行为，T/SCENARIO.md映射。只独立1GET/强opaque版本+rangeSHA/有限HTTP1解析与显式本机namespace适配，不扩大旧完整源校验、默认offline或MCP3工具。范围真值由system-test原AVI bytes/若干边界和确定性pattern先冻，synthetic不冒真实规模。Core Rust object_range模块/main/Cargo+现cli tests（不新增target）；DRI preview_launcher最小flag隔离、工程fixture、手册/API；非作者不在贡献集合。4槽含PM/≤2作者/heavy唯一，10:00架构留槽。

不变量：object≤32MiB/range及整body≤512KiB/严格1GET≤原2界/头16KiB64项/绝对10s/Rust512MiB4CPU/output2MiB。字节摘要和ETag只核选中range与条件版本，不认证未读对象或未消费TCPtail。按CL定义consume后关闭，正确CL+前L+tail可成功，不降格全部长流拒。TE/折行/歧义/弱错版本/错CR-CL/短错body/不支持编码/URI注入/超界拒；错误后合法恢复、真实timeout/INT/peer-close资源终态。旧坏源LIMIT0、完整query/media/湖和MCP必要回归，不复跑旧71/7视频大矩阵。

08:24:33新120min，首08:44:33/行为09:24:33/M包09:54:33/硬10:24:33，末30min退出。借前完整target/registry S0无损gzip+原SHA，57旧pair55857866B进入S0/保owner；唯一httparse1.10.1 archive/index/source已在S0，核实际license/checksum后0下载，Cargo locked offline。新native首相位先判≤1GiB及实S1新hash/全改写，再准完整clippy/test；不能继承635M旧rebuild或假定0改写。jobs1/原阈值，证据归档后guard退本片新test再下一clippy，成功clippy只退自身newcheckrmeta/保借前57。M归档退临时cache再Root第11包原sidecar/wholeC复制zip完整账，必要paired总≤64MiB明确源/持续账/下片S0。全时物理峰UNKNOWN/旧Q04 NOT_PASSED不改，不建遥测/删除平台。

普通适用core完整profile实核、normalhook+postH、checkpoint/taskfinish、pushPRmerge、fresh detached精确M/新包/原sidecar/一次System3.9独立prefix公开入口+旧SDK兼容。用户bundle≤4MiB/referencefixture无ignored TASK依赖，server是临时工程本机namespace非部署；完整所有fixture/controller/socket/C/W/source/cache/两树清单guard退出后固定REPORT-CLEANUP-BOUND→最后纯读→SEAL。当前仅前置/合同，不提前宣功能/预算PASS。

原plan对新工程fixture路径确实拒绝；仅在stages.ACTIVE_FILES追加scripts/local_http_fixture.py精确路径，保持原6suite8命令/预算/阈值与未知路径继续拒绝，交非作者复核，不泛放行scripts。固定10s不新增caller超时字段，旧接口不变。
