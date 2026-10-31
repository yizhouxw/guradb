# ADR0049 固定对象完整源SQL与按需列

状态：已接受；受限实现。复用ADR0048局部片段验证和共有Rust SQL；显式新source DTO无物理选择，完整全组必要列通过已验证Prepared表达式依赖，不自建SQL解释器。只支持共有基础投影/过滤/源列排序/LIMIT和WHERE值参数，aggregate/distinct暂拒；物理预算不可执行明确拒。原parquet-read保选择合同，所有旧完整源hash不变。

不可变：source/etag/footer/全集chunk映射/<=200全源行数，投影+WHERE+ORDER依赖不漏，3组2列8GET而3组3列11拒；无行组裁剪，不将provenance整SHA写运行校验。沿共享bounded/page/sparse64M模型和SQL32M池/10s，newlauncher只newcmd，oldnetworknone。边界/准备成本/拒绝与验收见用户页及新目标TASK；必要独审先于实施，最终有限资格按精确H/M/新包另判。
