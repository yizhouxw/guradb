# ADR0047：受限本机HTTP固定版本Range

状态：受限实现与非作者候选运行验收通过；2026-10-31。必要设计复核ARCHITECTURE-DESIGN-REVIEW无阻断，不替代10:00静态槽或实际验收。

独立object-range --request JSONv1，不接旧SQL/媒体/湖/view，不新增MCP。字段origin/object_key/etag/object_bytes/offset/length/range_sha256；整数不接float/bool，未知/重复字段拒。origin精确http://127.0.0.1:显式1024..65535，object_key相对安全ASCII分段拼/objects/，ETag非空强quoted opaque≤128，无DNS/TLS/proxy/认证/重定向。范围checked且object≤32MiB/range1..512KiB。

选择现锁http1.5、同步std::net::TcpStream及预存官方httparse1.10.1（MIT OR Apache2、0普通依赖、archive45190B与index checksum核同），复用既有Tokio operation监督。0新下载/不改registry缓存，Cargo locked offline。1GET、不HEAD/retry/redirect；Range/If-Match/identity/close。逐byte读取有界CRLF头避免body read-ahead，只httparse一次，HTTP1.1/206且关键头各唯一/casefold、CR/CL/ETag精确，无TE/Trailer/obsfold/bareLF/multipart/不支持编码。按CL恰消费L并drop，无EOF探测/复用，不认证未消费tail；CL=L+正确前L+tail是可成功range的独验案例，不能谎称全部超长stream拒。错误前不publish，rangeSHA非整对象SHA，ETag后端信任边界与未读部分明确。

单request输入16KiB/头16KiB64项/body≤512KiB/output2MiB/绝对≤10s与原Rust512MiB4CPU不扩。socket无后台网络task，正常/错误释放连接；取消沿既有监督退出进程并由OS关闭socket；组件资源/服务端write/客户端consume分别记，不冒网卡/数据库性能。

预览显式--local-http-container full64hex只准新命令；同localUnixDocker inspect Running/image09bc/networknone/noPublishedPorts/工程label v1，精确ID join namespace，无hostnetwork开关/出网fallback。产品2mount仍prefixengine+显式data，旧offline/MCP3工具不改。工程fixture用既有image内stdlib Python、networknone/127.0.0.1临时服务/只读capture对象，产品Rust不监听，不恢复历史Python在线。target容器生命周期由caller保留，stop/restart/race明错，不作为多租户安全/权限平台。

独立原source/range+HTTP拒例真值先冻结、真实client/server请求计数/错版本/假range/短错读/超时cancel恢复，再normal原B-H-M及第11包/原sidecar/唯一System3.9installed入口与旧CLI/MCP必要兼容。只core-limited；S3/远端湖/SQL按需扫描/一般HTTP与性能规模未支持。
