# 完整源投影SQL首片计划

目标：显式source无物理选择→固定HTTP metadata全schema/行数→共用Prepared/typedparams→所有group的真实依赖列→原bounded/稀疏Arrow批→共用DataFusion SQL/标准结果+局部读证据。

DRI独写用户合同/新helper模式/API/launcher/示例与交付工程；Core独写Rustprojected/sql必要适配与测试，不改SQL语义；ST非作者独立全读SQLite/rows/column/GET真值与候选/精确H/M/唯一fresh/最后纯读；架构单必要设计后停。最多四槽含PM，至多两作者，heavy唯一，编译前target/registry完整R01 S0，57pair连续保护。0新依赖优先。

预算/拒绝：保持全部旧界/8GET512K10s/64M+32M/200源行beforefilter，元数据+所有依赖chunk计划不适配即拒；不漏ORDER/WHERE、不把物理子集当表、不重置工作集预算/不静默fallback。失效版本/映射/超行/参数/未知AST/所需encoding/0limit必要拒、真实cancel/pipe/recovery。重大cache/包C阶段先准入再做，原日志归档后只guard新test/check物，Rootzip与Czip独计。原失败与UNKNOWN保，hard13:33:20，12:33行为冻、13:03M包、最后30min退出；完整资源峰UNKNOWN就不授整段PASS。
