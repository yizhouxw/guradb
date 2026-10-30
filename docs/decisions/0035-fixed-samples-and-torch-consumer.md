# ADR0035：Rust固定成员与asset组划分，真实框架消费

状态：已接受，2026-10-30；固定数据/真实reader有限独验PASS，非训练结果或发布认证。

显式DocID选择仅由Rust在同一SHA固定Parquet中验证，request v1包含format_version/source_sha256/seed u32/doc_ids唯一集合，≤64KiB/200Doc，错源/非法/重复/未知/空/版本拒绝。至少2独立asset；SHA256 ASCII `guradb-sample-group-v1\n{seed-decimal}\n{asset-decimal}\n` 的digest字节排序/确切tie数字assetID，最低1asset validation、其它train，每split按DocID ASCII升序。只包含明确选择成员，不自动扩同asset其它caption；同asset不得跨split，不足group拒绝。不承诺任意不同seed必变，因为集合有限。

Rust sample输出显式版本/source/request摘要/seed/算法/组次序、两个split原text与media身份，模型明确not_used；固定成员时校验所选原media bytes，发布前核source/selection，后续media以固定source和asset摘要读取。没有共享pin/lease/GC/训练平台；caller保源，删除/替换/混源明确失败，两次校验之间修改再恢复不保证侦测。原CLI/预算保持，无SQL、模型、ANN或生产Python扩张。

PyTorch Dataset/DataLoader只取Rust两个数组，逐样本调用原media，不另做选样/组划分/查询；同源原字节SHA/文本/DocID、固定Pillow13 RGB-bilinear32-uint8 CHW、无model/encoder。单进程num_workers0/shufflefalse/drop_lastfalse、两epoch/batch1..8，真实尾批/每成员顺序可核。受支持环境复用现Macarm64 CPython3.12 Torch2.15/Pillow13锁，不下载依赖、模型、新媒体或云费用。

客户端manifest≤1MiB，两epoch返回media应用payload≤32MiB；采样初核另≤3×512KiB，不冒总I/O。reader工作120秒、单进程RSS4GiB/计算线程4、父250ms采样加子OS历史峰值，非OS硬RSS配额；失败清理另≤30秒。每Rust调用有唯一owner PID label和容器finally清理，停止worker后父按其精确label清自有container；fresh输出不覆盖、错误/取消/输出失败清本次所有权。模型cache/env/既有20file bundle保护，临时副本按归属回收。

只证明选择/数据消费可复现，不等于训练结果/准确率/全M1/P0或发布。独立truth从原Corpus成员与asset映射在看实现前冻结；两个seed/最小子集/不泄漏、真实两epoch/尾批、错源/缺失同长替换/坏选择/预算/取消/恢复，分别验收，不借前包模型数值/旧LIKE矩阵冒当前通过。
