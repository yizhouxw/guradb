# ADR0032：固定Parquet上的有界ASCII BM25

2026-10-30，已接受；独立数值/真实源与生命周期验收通过。每唯一doc_id/text一文档，text_version=1；可选完整media-v1同源绑定，
image/caption不隐合，input/helper接受真实用户JSONL/本地文件，不以COCO preset代替输入能力。
ASCII alnum lowercase、无stop/stem，固定k1=1.2/b=.75与positive IDF，完整公式/所有拒绝和预算以用户手册为准。
参数与positive IDF参考[Lucene官方BM25说明](https://svn.apache.org/repos/infra/sites/lucene/core/10_3_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)，
本合同明确包含tf*(k1+1)归一项；不声明跨引擎数值兼容。
运行时Rust从同固定Parq流式计query TF、全Corpus DF/dl/avgdl并排序，非持久索引；≤200doc/256KiB text/65536token/8query词，
保原源/解码/输出/期限界。返回原文/ID/贡献/同源media身份，media命令才验证实际bytes，无模型/ANN/网络/目录平台或新增依赖。
数值reference与人工相关性标签分开验，不由算法PASS推定业务收益。normalhook/非作者/原B H-M/root与回收保持core-limited。

排序按实际f64总序，仅实际相等分数按稳定ID；相同TF/dl/stats保证同分。数学等价不同加法路径可能有末位差异，不用容差强合并，数值truth容差保持原值。
