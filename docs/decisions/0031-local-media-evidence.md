# ADR0031：媒体身份内嵌固定Parquet，Rust返回有界证据字节

2026-10-30，已接受；真实原源字节、拒绝与生命周期已独立验收。延续ADR0028及0030，单可信用户/单本地Parquet/Rust进程。
命中source_sha256与asset ID为media请求必填，config SHA绑定同Parquet里的image_id/image_path及
media_version=1/media_bytes/media_sha256；不把可变source.json或外部manifest取latest当权威。
版本1只容纳3资产/200行，正12位ID、images/12位.jpg，相同ID多caption绑定必须一致。

Rust使用目录FD/openat O_NOFOLLOW逐级打开images和该JPEG，拒绝链接/特殊文件/越根；
最大512KiB，校验大小/SHA并再次核Parquet后返回原bytes的hex及身份JSON，原2MiB输出与期限不变。
选stdout，CLI无用户文件/临时文件写入，--output拒绝；完整JSON+exit0才成功，部分stdout非成功。
超时/取消由原进程监督退出，RAII与OS回收FD/内存，无新持久发布协议、后台资源或spill。
仅给锁中已有libc增加直接归属以实现此Unix文件打开，不引入目录/权限/远端平台。
离线prepare显式evidence模式增加三列，旧默认不变；新模式按固定JPEG hash复用此前解码事实，不重复解码。
原源真值、替换/错绑定/越根/超限/未知版本/无输出覆盖/真实取消与重跑独验，core-limited不冒发布通过。
