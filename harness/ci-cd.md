# 基于 GitHub Actions 的 CI/CD

GitHub Actions 作为本项目 CI/CD 的推荐执行平台。当前已有[质量工作流](../.github/workflows/check.yml)，私有远端已配置，此前[bootstrap首跑](https://github.com/yizhouxw/guradb/actions/runs/39018367247)已通过。本轮M0增加固定Docker构建及真实S3/PG组件验收，尚待推送后验证；发布产物和部署环境合同尚不存在，不创建返回假成功的部署步骤。

## 已配置的 CI

| 入口 | 实际范围 | 执行与证据 |
| --- | --- | --- |
| pull_request | PR base 的 merge-base 到当前测试树 | 本地同一 harness，锁定依赖，Python 3.11/3.14；新 PR 运行可取消旧 PR 运行 |
| push | before 到当前树；初次 push 全树 | 不因本地干净而误用空差异；保留失败日志 |
| workflow_dispatch | 默认 `base=all`；可明确选择已有 base；scope 为 change/release | 全树检查已提交代码，release 缺任何必需运行时 suite 都失败 |

普通检查250分钟、release 360分钟是当前job上限，不是产品性能目标。按policy实际ready命令数×单命令超时并保留600秒安装/上传余量计算串行上界；普通检查保守计全部ready suites，包含Python和Rust。planned套件立即记录missing、不启动命令，因此没有虚设的一条执行时间，release仍因missing失败；未来变ready并配置命令时必须计入，超限须分段。当前全部ready及余量为14820秒/247分钟，unit-coverage工程watchdog为900秒，既有组件/工作负载阈值不变。GitHub-hosted job受[官方6小时上限](https://docs.github.com/en/actions/reference/limits)约束，自测拒绝写入超过360分钟。冷编译或工具安装超过预算明确失败，远端尚未验证，不能把本地缓存运行当作CI时长证据。完整性能/长稳接入后按受控硬件、对象区域和拓扑拆分专用job/runner；共享hosted runner只证明基础和smoke验证，不建立产品性能基线。

权限仅 contents:read；Actions 固定 commit SHA，checkout 不保留写凭据；输入经 env 和带引号 argv 传给 harness，不将任意 ref 输入拼入 shell 代码。所有必需门禁禁止 continue-on-error。报告在 always 路径上传，matrix 产物各有独立名称；普通 push/release 不通过新任务自动取消。依赖安装或 runner 被中止时可能尚无报告，必须查看 Actions job 状态，不能以“没有红色报告”当通过。[工作流语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。

## 建立远端后的接入

1. 已建立私有仓库和远端；2026-10-20用户已授权后续开发提交经本地验证后直接推送现有origin，推送任务分支并创建PR，满足[并行流程](parallel-development.md)后通过GitHub合入main，无需逐次确认；不直接推送主线。推送后核对对应commit的Actions状态；远端设置与部署仍另行授权。
2. bootstrap push运行已通过；M0需在推送后验证运行及失败日志上传。配置所需检查为两个 Python quality job，限制主分支写入/合并权限；根据平台方案可用性设置对应保护，不把仓库内 YAML 当成远端权限已生效。
3. 为 harness、CI、依赖基线、格式/提交协议建立审查责任；真实内核落地后逐项将 planned 变成真实 gate。性能/故障 runner 的网络、配额、对象前缀和清理预算先冻结，外部 PR 不直接运行有凭据或持久访问权的 self-hosted runner。
4. 明确证据长期保存位置与保留期。当前 Actions artifacts 14 天只是诊断保留；候选发布和性能基线到期前归档到授权的持久位置，不能只保留 URL/摘要。

## PR 合入门禁

所有开发通过 PR 合入 `main`，工作分支 push 的成功不能代替 PR 测试合并树通过。必需检查精确对应 `quality (Python 3.11)` 和 `quality (Python 3.14)`，核对当前 head/base、两个 job 的结论及未解决审查；主线更新后先 merge 最新 `origin/main` 并重验，再串行合并。当前不启用 merge queue/auto-merge；若以后启用 queue，须先补 `merge_group` 事件、其基点选择和真实测试，不能只更改远端设置。

远端保护的具体设置、单人审查边界与核验表见[PR并行流程](parallel-development.md)。本轮仅落地仓库约定和模板，不声明保护已生效，不修改仓库权限或保护设置。

## 后续 CD 接入合同

有可部署服务和明确目标环境后再实现：固定 source commit → 真实构建/测试 → 生成带版本/依赖与校验的不可变产物 → 完整发布门禁 → staging 部署/恢复 smoke → 用同一 digest 产物晋升生产。禁止在各环境重新构建不同字节却仍视作同一发布。

staging/production 通过独立的 GitHub Environment 绑定授权、环境配置和保护条件，按平台方案可用性设置 reviewer/分支限制；生产并发串行且不取消进行中的部署。部署身份仅在对应 job/environment 授予，云平台可用时采用短时身份联合，凭据不进入代码、tag 或日志。[GitHub 部署环境](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。

晋升前记录部署版本、产物 digest、数据/索引格式及迁移前提、兼容窗口、pin/进行中作业、备份点、健康与恢复断言。失败时保留日志并停止晋升；应用可回退到已知 digest，持久数据按具体迁移/对账方案恢复或向前修复。CD 重试必须有部署操作身份并检查已执行效果，不能靠盲目重跑假设撤销了业务副作用。

当前缺少发布构建/容器registry、目标运行环境、部署身份、健康/数据恢复合同及实际 release gate；这些是进入 CD 的实施前提，不阻止现有文档与 harness 开发。

本地P0/HTTP worker、离线恢复与状态检查曾将job预算更新到change240/release360分钟。本轮覆盖工具watchdog与实际ready执行模型修订后普通job为250分钟；完整suite义务及每项预算未减少，尚未实现的release门禁继续missing。新driver增加实际命令时必须重新核对预算，不能复用旧时限通过结论。远端运行需按当前已授权的提交推送后核对实际结果。

## 模块交付 v2 的调度合同

[策略 v2](../docs/plans/2026-10-21-modular-delivery-v2.md)要求 pre-commit/PR 使用 auto 映射模块或真实配对，工程工具有专属机制自测，系统候选在 main 集成窗口验证；release 仍包含所有 planned 义务并对 missing 失败。gates-v2 的工作流实现必须保留 Python3.11/3.14 两个 quality 名称、当前 test-merge 检查、固定 Actions SHA 和安全证据上传，不通过旧绿/skip 冒充新层级。

手工运行将接受明确 level/modules/base 与可选 batch 标识；实际字段名以独审后的 CLI/workflow 为准。报告记录本次选择原因、完整模块分母/排除、配置/选择算法指纹、真实 argv/timeout、耗时与源码闭包，不能 module→system/release 降级伪造。main 第一版仍执行 system；ROOT 通过批次组织减少无意义候选。未启用定时回归、未运行 release 或未认证远端设置要明确 pending，不仅凭 YAML 存在宣布通过。
