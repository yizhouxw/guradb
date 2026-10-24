# 固定版本对象与可信范围读取

状态：**恢复树原始范围 INITIAL 九项门禁已通过，最终交付待完成**。本机Python3.14完整232项单元（含26项固定对象单元）、Python3804/3804零排除、Rust3323/3323（保留原21行豁免）及真实功能/成本/故障driver均通过，root已独立核验。该次证据绑定28文件manifest `64f1cd3aab20ce86212968193654bb3c4bb2a3e42a21dc372bb6afd9a922c765`、checkout `e8798305c8b4fd87d31296e8c42fe3b94386c1432c3ae2ec52a4e3c04af59998`；本次仅更新结果文档，后续最终提交仍需精确绑定的新检查。源码、输入及报告见[变更计划](../design/fixed-objects-change-plan.md)。这是 CF1-A 的 storage 模块入口，尚未接入 SQL/HTTP、真实 P04 源 reader 或 PG 目录，不代表完整P03、I1、真实云或多机认证。hook、提交后原范围检查、task-finish、PR/主线CI及实际CI上传ZIP核验仍待完成。验收映射见[场景表](../design/fixed-objects-scenarios.md)。

## 场景与前置

读取已绑定视图中的一个固定 S3 VersionId，覆盖同 key 后仍取得旧版完整字节；或凭可信登记的完整块表取得对齐的完整块。读取必须匹配版本、大小与 SHA-256，缓存命中也重新检查当前目录授权。

调用方提供冻结的 CF1-A ReadBinding/ObjectRef、一次查询共用的累计 ReadScope、可信后端配置、内存凭据快照、当前授权 callback、取消事件和可信 proof authority。storage 在成员校验时从已授权规范字节取得私有 ObjectRef 快照，授权 callback 或传输途中修改调用方字典不能改变该次读取的 key/version/SHA/块表，也不能污染原固定键缓存。ObjectRef、pin、proof_ref 本身不授予权限。首片 callback/registry 仅允许有界本机内存实现；本机 fixture 不能冒充目录权威或真实 PG 授权。

Python 3.11+；依赖采用仓库锁文件中的 botocore 1.40.76。真实验收使用锁定 SeaweedFS 3.97 镜像和单个 m0-data bucket；每次 run 使用独有前缀，避免 Lab volume.max=1 的第二 collection 限制。

## 操作与预期

当前候选的模块组合方式如下。变量均来自可信执行入口：binding 为已验证 CF1-A Contract，ref 逐值属于该 binding，catalog_reauthorize 验证当前签发/授权状态并返回 epoch；trusted_block_registry 仅来自可信登记，不能复制请求自报的块表作为证明。日志规则须先由组合根固定。

```python
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_proofs import ProofAuthority
from modules.storage.fixed_scope import ReadScope
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend

scope = ReadScope(binding, cancelled=cancel_event.is_set)
backend = FixedBackend("local_s3", "m0-data", endpoint,
                       CredentialSnapshot(access_key, secret_key),
                       versioning_certified=True)
reader = FixedObjects(scope, {"local_s3": backend}, catalog_reauthorize,
                      proofs=ProofAuthority(trusted_block_registry))
data = reader.port.read(binding, ref, 0, ref["size_bytes"])
usage = scope.usage()
```

versioning_certified 只能由完成本轮实际后端认证的可信配置给出，不能由 ObjectRef 或外部请求设置。首片 backends 必须是恰好一项的普通 dict，key 与明确 FixedBackend.backend_id 相同；bucket 固定 m0-data、region 固定 us-east-1，cache 容量最多256KiB。一次查询中所有对象复用同一个 scope；当前保守保留所有已返回 bytes 的内存成本，不能重建 scope 绕过累计额度。该候选接口不是已集成的 SQL/HTTP 产品入口。真实验收命令为：

```sh
.venv/bin/python scripts/fixed_objects_acceptance.py --suite functional --run-dir artifacts/fixed-objects-functional
.venv/bin/python scripts/fixed_objects_acceptance.py --suite performance --run-dir artifacts/fixed-objects-performance
.venv/bin/python scripts/fixed_objects_acceptance.py --suite faults --run-dir artifacts/fixed-objects-faults
```

上述三driver已在本轮原始范围完整INITIAL中重新运行成功，绑定manifest `64f1cd3aab20ce86212968193654bb3c4bb2a3e42a21dc372bb6afd9a922c765`、checkout `e8798305c8b4fd87d31296e8c42fe3b94386c1432c3ae2ec52a4e3c04af59998`；完整报告 `artifacts/harness/20261021T053114Z-e7619721/report.json`，三driver结果位于同目录的 `fixed-objects-{functional,performance,faults}/result.json`。旧7fd121/8e8732局部结果继续保留为历史证据，不复用于本轮。本文随后仅更新结果，不能把新文档SHA称为已检查源码。成功返回全部请求字节或完整对齐块，不返回部分成功。报告记录scope实际接收header/body/wire、校验和输出、累计attempt、内存/缓存、进程RSS、原截止与monotonic锚、最后正接收/关闭/观察返回时间；代理/故障server的sent另列，未被应用recv的内核字节不伪报相等。

## 首片白名单与拒绝

| 项目 | 本轮模块验证范围 | 明确拒绝/后续 |
| --- | --- | --- |
| 后端 | 可信配置的 http://127.0.0.1:port，path-style，单个认证 versioning bucket | DNS/IPv6/非 loopback、TLS、真实云、代理发现、任意 endpoint/Host/region、虚拟主机 bucket |
| 请求/响应 | GET、非 null 固定 VersionId、整对象或单 Range；有限 HTTP/1.1、唯一 Content-Length、连接关闭后 EOF | latest/null/unversioned、未认证 versioning、重定向、压缩、Transfer-Encoding/chunked、HTTP/2、1xx/升级、无长度、连接池 |
| 对象 key | 真实固定GET覆盖空格、UTF8、字面百分号/加号、重复斜线；字面%2E编码/读取单元通过 | `key.split('/')` 中实际 `.` 或 `..` 段在签名、I/O和缓存输出前 unsupported_capability；不归一化或替换key，字面 `%2E` 不等同实际点段 |
| 完整性 | whole_sha256 仅整对象；block_sha256 可信完整块表、整块及短尾块 | 整对象摘要证明局部范围、ETag 当 SHA、自签 proof、错对象/版本/表、缺块、非对齐范围 |
| 缓存 | 有界内存不可变缓存、固定身份/摘要隔离、每次输出重新授权 | SSD/共享缓存、缓存绕过撤权、后台预取/合并、多机资源调度 |
| 同步入口 | 普通无 running event loop 的调用线程；一个 scope 串行多次读 | 同线程已有 event loop 时在 I/O 前拒绝；隐式线程化/嵌套 loop、同 scope 并发 |
| 凭据 | 私有可信内存快照、错误access/secret真实拒绝、过期/暖缓存拒绝；session token仅签名注入/日志单元验证 | common封包带密钥、环境/IMDS/profile/STS自动发现或刷新、实际临时凭据服务与token后端认证、认证失败盲重试 |

这些结论限固定镜像、单bucket、本机loopback和本文白名单；Python3.11/3.14分支CI、其它后端与完整产品入口尚待验证，不从旧SDK probe扩大本轮结论。

本轮固定SDK→固定Seaweed的 `dot/../path` fixture PUT 实际返回403/SignatureDoesNotMatch，未能建立该key的可认证固定版本；该结果不是新GET transport的认证。首片明确拒绝实际点段，保留原PUT作为真实后端拒绝场景；模块另用明确negative-only的描述符验证请求前拒绝与0 GET/输出，不冒称其占位版本是后端真实版本。P03完整目标义务保持，后续支持该key须重新认证。

## 权限、预算与取消

首片的 reauthorize/cancelled 回调仅接受可信、有界、无阻塞 I/O 的内存实现。真实 PG 授权尚未与本组件配对；后续集成必须传递原 monotonic 剩余期限，实测 PG 暂停时的整个授权、对象读取与清理路径，不能直接注入网络回调后沿用本片结论。

读取前和返回前均由注入 callback 验证当前 policy epoch；撤权、过期、取消、校验失败或资源不足均不给成功字节，缓存也遵守。每次 read（包括已暖缓存）均检查私有 credential snapshot：若声明 expiry，必须覆盖原固定 query deadline；过期或短于 deadline 均 unauthorized，不因本次无需签名而绕过。取消状态 callback 异常按脱敏 cancelled 失败关闭，并终止所属 I/O，不把原始异常交给 asyncio 日志。后端认证与目录授权分别验收。认证后固定版本 404 为 missing_object；401/403 为 unauthorized；429/503/暂时连接不可用只在原剩余额度内有限重试；错误版本/长度/SHA 为 corrupt_object。

ReadScope 在查询执行入口建立一次。所有 read、attempt、失败接收、校验与清理累计，不逐调用重置。绑定中 `deadline-bound_at == remaining_ttl_ms` 且最多 30 秒，binding 保持不可变；本地 monotonic 剩余时间只减少。整体 deadline 包含连接、持续首部/body 滴流及 EOF，不是每次 recv 的 idle timeout。

首片输入上限 8MiB，64KiB body chunk、最大 32KiB 首部/8KiB 单行/64 字段、16KiB 请求；默认 cache 256KiB、最多 3 attempts。实际 context 的请求/body/output/内存额度更小时优先约束。EOF 探测预留额外 1B 潜在 body 额度；接收 buffer 转不可变 bytes 的瞬时双份及已有 cache/proof/返回字节都计内存，16MiB context 不保证可读任意 8MiB 对象。

I/O在原deadline之前预留200ms同步处理/清理余量，不足250ms准入余量先拒绝。本轮700ms绑定下，首部/body停顿、持续滴流及缺EOF五场景含server清理约502.55–507.95ms；首部/body/EOF三场景取消含清理约5.90–16.04ms，满足预冻结100ms目标。报告保留原deadline、最后正接收、关闭与观察返回；循环/取消callback异常和已有event loop拒绝有独立单元。真实连接停顿、非loopback/TLS和PG网络授权尚未认证，Python/OS调度不是硬实时保证。后续失败保留证据，不抬预算或缩小输入。

## 日志与恢复

锁定 signer 的 DEBUG 会记录 canonical request/session token/signature。实际组合根必须在首次签名前固定配置禁止 botocore.auth 调试输出；storage 库不永久或临时修改全局 logger。验收在 root DEBUG 与失败路径捕获 canary secret/token/签名及 URL 密钥泄露，代理不落原始请求首部；此日志配置是认证前提。

本片只读，不写生产对象、发布、GC 或删除；旧 M0/M1/M2 读取保持兼容。丢弃缓存后重新校验同一固定版本；对象消失或校验失败不切 latest。失败保存脱敏报告和故障 trace，Lab 的测试 PUT 与容器资源独立清理，不把代码回退当作撤销外部副作用。

## CI fixture错误诊断补充（单元通过，完整门禁待验）

旧PR12两版CI在dot fixture PUT捕获ClientError后未满足精确SignatureDoesNotMatch/403要求，裸断言丢失了实际code/status；CI具体错误仍未知。本机同固定index的linux/amd64窄诊断仍得到该精确403，没有复现CI失败，也不能据此断言架构或SDK根因。已完成本地读取证据与旧PR失败都保留。

本轮仅调整验收fixture：四个特殊key和原负载/门限不变；只有dot的精确SignatureDoesNotMatch/403可进入原negative-only模块拒绝路径。其它ClientError继续失败，但通过既有脱敏FixturePutFailure写下受限case、stage、后端code和HTTP status；任何dot PUT意外成功仍失败。不会记录原始异常、URL、SDK响应/Message/headers/operation_name、签名或凭据，也不扩大固定对象读取能力。新增7项单元已在本树新venv实际通过，真实CI诊断与完整门禁待运行；修复诊断丢失不等于CI原因或失败已解决。


本树首次定向单元窗口（2026-10-21）：独立新venv按三锁安装并pip check通过；`.venv/bin/python -m unittest -v tests.unit.test_fixed_object_fixture_put` 实际7项全部通过（unittest3.658s，外部3.810795s）。结果位于 `artifacts/p03-ci-fixture-diagnostics/unit-first-20261021T095157Z-790e530e/result.json` SHA `1c4d2676f5c6cb8d15ae5fb399439b3bb1c2864b9d6cc890cb4fc9d6e4a9024a`，window-result SHA `61911659d9ef5c05202725572b457654845ef1ead15491ed6429b1f6ee84d286`。39源码/5dirty/receipt/index前后未变，随后仅更新本三结果文档。单元使用真实ClientError类和mocked服务/driver环境，未运行实际S3/SDK网络、Rust或完整门禁；target仍不存在。原4d完整normalhook/post、私有raw保全、PR与精确main/双CI待验，PR12实际后端code/status与根因仍未知。
