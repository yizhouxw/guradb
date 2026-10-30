# 本地stdio MCP预览（本机受限SDK已验）

固定MCP 2025-06-18，只支持可信单用户、本机Mac-arm+既有LinuxARM Docker、显式绝对路径非链接store。Rust唯一数据执行权威；首片仅view query/search/media三个只读工具，共用现Rust CLI子进程。vector/hybrid/sample、prepare/publish/recover/delete、任意文件/命令/URL、HTTP/auth/全局MCP注册未支持。direct CLI不变。

公开启动：`guradb --data-root "$USER_DATA" mcp --store /data/store`（本包fresh安装物，不覆盖旧797b包）。官方Python SDK mcp==1.12.4、独立CPython3.12标准客户端验证；SDK仅工程客户端，不进入生产安装物。stdout仅UTF8一行一JSON-RPC，日志stderr，不输出用户参数/媒体日志。initialize协商server仅2025-06-18，有效但不支持的提议回报该版本；initialized通知后才tools/list/call。无prompts/resources/sampling等能力，不以忽略冒支持。

工具`guradb_query {view,sql}`、`guradb_search {view,query}`可用current或显式64hex ID；`guradb_media {view,asset_id}`必须显式固定ID。响应content[0].text为原CLI完整JSON，包括实际view/source/文本/分数/媒体bytes_hex，读者先parse再用返回view取媒体；不得把current当跨调用固定ID。工具参数/unknown tool是协议错误，Rust实际拒绝是isError=true且原code保留，不截断假成功。外部公开CLI刷新current后原ID读取固定旧内容。

请求ID仅整数或≤128 UTF8 bytes字符串（含空串），会话内唯一。host仅64KiB原始字节缓冲，公开stdout逐响应帧写回限5s，不依赖Docker内部缓冲代表客户端已接收。会话最多60s/32条输入消息/8MiB总输出，单请求64KiB/单响应2MiB，单worker/单待写响应，无无界排队；忙时新调用明确拒绝。半行/空闲10s，写回5s，worker原Rust10s且额外清理2s，session终止清自己的worker；原源32/decode64MiB/feature8MiB/N200/维1..1024/TopK20与Docker512MiB4CPU不放宽。MCP专用launcher总75s+10s清理，原非MCP20s+10s不变；host SDK与Rust容器预算分列，不冒aggregate RSS硬限。

取消notification不响应，取消对应worker后继续会话；EOF/断连/坏framing/超界/写回堵塞/INT/TERM终止并清ownworker/container，同store重新启动恢复。输入通知不发response；未知request/method/参数/重复ID、非法版本类型、未初始化与不支持能力拒绝。SIGKILL/跨平台/任意客户端/完整MCP矩阵未认证，不修改用户全局配置或数据store。精确三工具已由独立官方SDK/CLI差异、真实current刷新、准确媒体与生命周期共同验证；完整MCP及其它客户端未宣称。


官方客户端最小复现（在独立Python>=3.10环境安装[锁定工程依赖](mcp-client-requirements.lock)，与数据准备/model环境分开；服务端不依赖SDK）：

```python
import asyncio, json, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    p = StdioServerParameters(command=os.environ["GURADB_ENTRY"],
        args=["--data-root", os.environ["USER_DATA"], "mcp", "--store", "/data/store"],
        env={"PATH": os.environ["PATH"], "GURADB_DOCKER": os.environ["GURADB_DOCKER"]})
    async with stdio_client(p) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print([t.name for t in (await session.list_tools()).tools])
            reply = await session.call_tool("guradb_search", {"view":"current", "query":"kitchen"})
            if reply.isError:
                raise RuntimeError(reply.content[0].text)
            result = json.loads(reply.content[0].text)
            if not result["result"]["hits"]:
                return
            asset = result["result"]["hits"][0]["media"]["asset_id"]
            evidence = await session.call_tool("guradb_media", {"view":result["view_id"], "asset_id":int(asset)})
            if evidence.isError:
                raise RuntimeError(evidence.content[0].text)
            data = json.loads(evidence.content[0].text)
            media = data["result"]
            import hashlib
            raw = bytes.fromhex(media.pop("bytes_hex"))
            assert hashlib.sha256(raw).hexdigest() == media["media_sha256"]
            assert len(raw) == media["media_bytes"]
            print({"view_id":data["view_id"], "identity":media})
asyncio.run(main())
```

自己的受支持store可由既有[固定view准备入口](simple-alpha.md#本地固定视图与完整刷新)产生；示例关键词由调用者更换，不含离线hit bool。客户端要检查isError、完整JSON与source/view/媒体SHA，不从另一asset成功推导检索证据链。
