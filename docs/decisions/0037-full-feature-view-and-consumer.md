# ADR0037：完整特征视图与固定消费

状态：已接受且通过本首片有限验收；2026-10-30。v1 source-only store保持既有3入口，v2新空store显式提供feature pin，view ID为SHA256 ASCII guradb-view-features-v2 LF sourceSHA LF featureSHA LF；feature pin覆盖完整source/Doc全集/space/model/preprocess，禁止原source-only ID补可变依赖。未知版本拒绝，无隐式原地迁移。

Record保存sourceSHA与feature SHA/完整typed Space；prepare校验并捕获source/JPEG/features全部bytes后才prepared，publish与每次read复核全部ready，任何缺失/替换失败，不回退旧feature。source+feature异源拒绝，query同source同space；原cosine/RRF60/fullrank不变。sample复用原Rust成员，输出精确view_id；client只固定首次Rust current结果，全部media传此ID，current刷新不得混源。旧direct config不变，无Python数据库/推理在线服务。

2views含pending/128MiBowned data/1MiBdescriptor/features8MiB/source32/decode64/output2/原行维度和期限守界。新catalog字段与features layout扩展公开recover/原子状态；空store升级v2发生在首次完整prepare，无旧v1数据迁移；KILL准备/提交未知与pending按新布局实测。old binary拒绝v2，caller保完整store/备份，无GC/pin/代际fence。

V1复用唯一已验15Doc/512D官方CLIP payload，V2四Docsource改绑不能手改真实model header；冻结必要性后只1次同revision同code原3图/≤8query CPU4/4GiB/600s离线export，无新下载。数值fixture另标数值，真实模型不做泛化或业务优势认证。非作者先冻原源与数学真值、跨current真实DataLoader两epoch/尾批及像素，source/feature错误和真实进程终态共同验收，正常原B/H/M/root链。

本片实际非作者验证新format2全rank/错误、三个真实KILL公开recover与真实两epoch跨current固定旧view通过；旧config最小兼容、取消/输出失败清理同验。仅core-limited；完整M1.5/安装MCP/断电平台等留缺证据。
