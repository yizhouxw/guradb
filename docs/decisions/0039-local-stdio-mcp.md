# ADR0039：有限Rust stdio MCP与同CLI只读执行

状态：已接受，本机受限三工具与官方SDK独立验收通过。冻结官方[MCP2025-06-18 transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)、[lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)、[tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)与[cancellation](https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/cancellation)。官方[Python SDK](https://github.com/modelcontextprotocol/python-sdk) 1.12.4仅独立工程客户端，PyPI来源/hash/wheel清单先冻后单套，SDK原依赖Pydantic2.14.2不兼容失败后同套固定2.11.7/core2.33.2，累计6.64MB，非Python数据库服务。

首片三工具query/search/media只适配显式store的既有Rust view argv。同executable有界worker，不再实现SQL/排序/源/媒体读取语义；单inflight/一个pending输出，非阻塞stdio使堵写期间取消仍可处理，返回CLI完整JSON。media必须固定view，当前检索结果中的具体view ID供后续证据，不捕获可变current作pin。其它六路以外/未接三路明确不支持，不宣称M1或完整MCP完成。

初始化协商只2025-06-18，notification无响应，协议错误与Rust执行isError分开；无全局注册/HTTP/外部文件工具。会话60s/32message/8MiB，request64KiB/response2MiB，读10s/写5s/worker10s+2s清理，原Rust/Docker资源界不改；launcher只有MCP分支75s+10清理与stdin透传，普通20s不变。终止/取消/EOF须等自己worker清理，新的fresh安装物与固定existing09bc逐身份独验（旧181已实际缺失，原包不改且另给fresh恢复包），不覆盖已有797b包。
