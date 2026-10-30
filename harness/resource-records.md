# 资源记录与只读 metadata 基线（v1，内部工程）

本入口仅内部工程，不改数据库、包装器、权限或运行预算；用于在现有guard退出前检查记录、记录有限快照及完整声明分账，不执行删除。旧I02各版证据/错误/历史峰值UNKNOWN保持，旧无版本格式首片明确拒绝，不自动猜pass/status或原地适配。

新stdlib入口`scripts/harness.py resources`提供严格版本化记录校验、bounded snapshot/diff和完整声明scope的ledger。schema_version/kind/status及所有必需字段/精确类型必须核；缺失、bool冒整数、未知版本、矛盾计数、未知/不完整组件不得默认成功，应输出明确结构化拒绝或UNKNOWN，不裸KeyError。canonical owner记录的实际字段以同步接口表为准，公开命令失败exit非0/无成功payload；validator从不删除私有或共享路径。

metadata snapshot默认最多50000条/深度32/输出32MiB/30秒合作式capture与encoding检查（不承诺中断kernel IO或强限fsync），explicit root与新out，lstat不跟符号链接、不读文件内容，无目录外扫描；超界拒绝partial完整声明。路径逻辑bytes与dev/inode去重bytes分列，硬链接不当成两份物理分配；目录/链接单列。采样期间非原子，前后观测/声明归属不是writer证明或历史峰值；即便两次低于限也永远peak UNKNOWN，不声称物理分配/全时段硬限。

任何shared cache写入/借用前先保存完整可核只读baseline。diff同一root身份（可显式记录同inode rename）、精确路径/metadata前后新增/消失/替换/原inode增长分别报告；没有实际baseline不能复原实际增量或“新cache”，默认未归属变化，不因mtime新就自动授权删除。若接受归属声明，必须显式版本/owner与路径/后状态匹配，不能把声明当系统鉴权。

ledger至少声明Root retained package和完整consumer temporary tree，后者包括copied zip、安装prefix、data、observer与其他全部临时后代；不允许用prefix payload替整个consumer。各root必须bounded full scan、无exclusion、状态完整；缺一项/矛盾/超界为拒绝或UNKNOWN。共享cache变化及其他声明root另列，不自动排除。该和仅声明观测scope；历史peak/未观察增长仍UNKNOWN，无全机budget认证。

验收：真实当前target只读metadata baseline；独立私有小目录前后new/replacement/growth/in-place/same-size、hardlink和symlink外部目标不跟随、完整包+consumer zip同时计账；真实文件在无效/未知/缺字段记录校验前后metadata和内容都不变。正例/拒例由非作者从实际文件和独立元数据真值核，不把作者输出expected。适用工程门禁/正常hook/原B H-M/PR保留；不是纯治理豁免，不跑无关产品矩阵，unknown selector扩大或拒。

## v1接口与含义

入口沿现有harness工程selector，不改门禁分类：

```sh
.venv/bin/python scripts/harness.py resources snapshot --root "$CACHE_ROOT" --out "$RECORDS/cache-before.json"
.venv/bin/python scripts/harness.py resources snapshot --root "$PACKAGE" --out "$RECORDS/retained.json"
.venv/bin/python scripts/harness.py resources snapshot --root "$CONSUMER_ROOT" --out "$RECORDS/consumer.json"
.venv/bin/python scripts/harness.py resources account --owner "$OWNER" --retained-package "$PACKAGE" --consumer-root "$CONSUMER_ROOT" --component "retained_package=$RECORDS/retained.json" --component "consumer_tree=$RECORDS/consumer.json" --out "$RECORDS/owner.json"
.venv/bin/python scripts/harness.py resources validate --record "$RECORDS/owner.json"
.venv/bin/python scripts/harness.py resources compare --baseline "$RECORDS/cache-before.json" --current "$RECORDS/cache-after.json" --out "$RECORDS/cache-diff.json"
```

RECORDS为已存在的记录目录，必须在所有被观察root之外；各out必须新建，不覆盖历史。snapshot对cache只读；需要借用cache的正常工程门禁须先存baseline、独占借还并保存after和归属差异，不能据此声称整段峰值已知。after由相同snapshot命令另取。PACKAGE是明确Root保留包，CONSUMER_ROOT是**整个**临时消费者根而非prefix子目录。caller须声明所有相关roots；工具不能发现被调用者隐瞒的外部临时树。根同inode重定位仅显式`compare --allow-root-rename`，不默认把新根当原baseline。

snapshot为schema_version1/kind resource_snapshot/status complete，entries无exclusions，root_before/root_after与totals/duration/limits完整，atomic=false。lstat只记录符号链接本身，regular路径逻辑bytes和dev/ino去重bytes分列，后者也不是物理分配证明。输出记录SHA可作为观测原件指纹，不能拿数据内容未读的metadata当content hash。

owner为schema_version1/kind resource_owner/status observed，owner明确ASCII ID，必填declared_roots的retained_package/consumer_tree，components按role嵌入完整snapshot，totals必须可重算一致；snapshot.root必须等于对应显式根，consumer必须目录全树。允许shared_cache/other额外分列，Root重叠拒绝。historical_peak始终UNKNOWN、scope=declared_roots_only、attribution=unattributed、deletion_authorized=false。**observed只表示资源账单观测/结构校验，不是已退出或已删除成功证书**；现有guard仍须自己核实时序/文件身份/退出事实。validate从不解释猜测旧pass/status结果，旧unversioned完整拒绝。

compare给出同基线/现观测的新增路径、同path换inode、原inode增长、删除及其他metadata变化（缩减属于metadata_changed）；这些是metadata事实和后续归属复核的候选，默认未归属，不能自动授清理权。即使before/after totals都小也historical_peak UNKNOWN；同大小原inode内容替换不读内容，仅能报告可见metadata变化，不能称检测任意字节篡改。

v1已由非作者以私有真实文件验证：40条CLI断言及超大记录读取前拒绝定向验证。输入JSON也限32MiB，超限文件按fstat在内容读取前拒绝。完整consumer含copied zip，硬链接分账、symlink不跟随、拒例文件不变及UNKNOWN语义已核；内部工程质量与数据库/发布质量分别记账。
