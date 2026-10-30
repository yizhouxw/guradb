# ADR0033：固定外部f64空间的精确cosine与全候选RRF

2026-10-30，已接受；独立几何/融合、外部接口和真实退出验收通过。独立feature JSONL由调用者固定SHA pin，header绑定同Corpus SHA/DocID全集/完整空间和来源声明，
query须同source/同space，未知/漏重复Doc/维数/非有限或零向量拒绝。数值接口不认证声明对应真实模型。
maxAbs-scaled L2归一、f64 dot clamp cosine，全量≤200doc/1024dim，最终TopK；不建ANN/在线模型或持久索引。
融合只用源内稳定ordinal rank，RRF60=sum1/(60+rank)，BM25空贡献0，向量全集完整，源不先截断；不加raw分数。
参考[RRF原论文](https://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf)固定形式，本文不继承论文业务效果结论。
复用同一次Parq解码和BM25评分，原32M/64M/2M/期限/no spill不变，feature8M/header16K/row-query64K。
两个公开外部数学输入及非作者先冻几何/融合truth、拒绝/进程终态与normalhook/H-M-root/清理验收；
真实模型有效性/权重来源与资源另列，不用数值toy冒语义/完整M1.3，no权重/媒体下载。
