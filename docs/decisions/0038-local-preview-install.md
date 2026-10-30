# ADR0038：有限本地预览包与只读诊断

状态：已接受，本机有限预览已实现并经独立消费者验证。生产engine仍Rust单CLI；stdlib Python只zip构建/安装/进程传输，不解析查询或存储。系统Python3.9+是公开先决，不用主venv。artifact携LinuxARM ELF与摘要/能力/来源/fixed localDocker imageId，不打包模型/env或Docker大镜像，不pull。host仅Darwinarm；不冒Mac原生/发行/MCP。

fresh prefix安装前外部trusted SHA验证；内部再校archive/所有固定文件/ELF arm64与schema，streamingstage→同卷原子不覆盖提交；存在prefix任何类型拒绝，异常只ownstage，提交结果未知公开doctor对账。升级并存/回退旧prefix，无全局PATH或数据变更。diagnostic读取安装身份/本地daemon-image事实，不读数据库/模型/发布数据；raw engine argv+显式data-root映射只挂已安装engine与用户数据，不复制DB语义。取消/timeout/outputfailure只清自己named container并保持用户store，原Rust退出码不吞。

archive1GiB/owned2GiB/build120s512MiB/install60s+10s/launcher20s+10s与Rust原预算保持。实际imageId而非tag，sourceengine tree+binarySHA与packaging codeSHA分开绑定；最终artifact从精确已审M生成。非作者freshHOME/cwd/无checkout-target-venv挂载消费者，只声明已持有Docker/image依赖，实际query/search/media/fullview/sample与负例/清理共同验收；不重旧模型/数值矩阵。SIGKILL/断电/跨平台未认证，checksum不是签名。
