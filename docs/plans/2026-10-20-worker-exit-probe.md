# 覆盖率中的真实 worker 退出诊断

状态：进行中。owner本CI修复任务；codex/worker-reproducer独占worktree；follow-up基点4332cb3；产品候选固定4828d4a，blocked-by PR3。PR4此前五次M2实验已停止；本次重新开放同一诊断分支调查新的明确失败，不合入main，不改变产品/原门禁/预算，无用户文档影响。

新证据：4828d4a push运行39365535263 Python3.11 contracts通过，但unit-coverage实际测试test_real_workers_share_remaining_source_budget的complete-workers返回worker_failed。覆盖比例Python/Rust已满，故不能通过豁免覆盖或重试消除。旧有临时fixture清理使诊断文件丢失。ARM Linux连续探测暂未复现，不能替代GitHub x86。

workflow先保存本分支诊断helper至RUNNER_TEMP，再checkout精确4828d4a；安装同锁，按原coverage配置运行同一真实测试最多300次，首次失败即停并保持非零。在unittest.addError（cleanup之前）仅复制固定诊断文件名、最多16个/每个8KiB，保留原错误，不留任务input/环境。输出实际SHA/Python/架构/次数，任何通过采样不声称根因解决。作业90分钟大于3600秒+30秒清理+600秒证据余量，上传14天。

自测验证固定SHA/action/最小权限/无重试及错误退出；真实文件fixture验证日志尾部有界、输入不复制、记录错误未吞。替身只验证诊断编排。四套plan/check、hook和提交后check/checkpoint后推送Draft诊断PR；需新源码候选时更新冻结SHA重验。现场停止用task-abandon，保留分支/产物；无数据迁移或外部补偿。

为保留原覆盖率进程的模块导入/测试顺序上下文，先按原runner顺序执行全部contracts+unit，再追加最多300次目标测试；沿用首次失败即停。没有更改被测源码、加载顺序、预算或失败判断。
