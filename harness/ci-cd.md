# 基于 GitHub Actions 的 CI/CD

GitHub Actions 作为本项目 CI/CD 的推荐执行平台。当前已有[质量工作流](../.github/workflows/check.yml)，远端仓库尚未配置，所以只有本地检查和 YAML/流程约束验证结果，不能声称 GitHub 上已运行。数据库构建物/服务及部署环境尚不存在，不创建返回假成功的部署步骤。

## 已配置的 CI

| 入口 | 实际范围 | 执行与证据 |
| --- | --- | --- |
| pull_request | PR base 的 merge-base 到当前测试树 | 本地同一 harness，锁定依赖，Python 3.11/3.14；新 PR 运行可取消旧 PR 运行 |
| push | before 到当前树；初次 push 全树 | 不因本地干净而误用空差异；保留失败日志 |
| workflow_dispatch | 默认 `base=all`；可明确选择已有 base；scope 为 change/release | 全树检查已提交代码，release 缺任何必需运行时 suite 都失败 |

普通检查 90 分钟、完整 release 240 分钟是 job 上限，不是产品性能目标。自动测试对照各 suite 的命令数×超时预算并预留安装/上传时间；新增 driver 使预算不足时需拆 job 或调整合理上限，不删除必需验证。完整性能/长稳接入后按受控硬件、对象区域和拓扑拆分专用 job/runner；共享 hosted runner 只为基础和 smoke 验证提供环境，不据此建立产品性能基线。

权限仅 contents:read；Actions 固定 commit SHA，checkout 不保留写凭据；输入经 env 和带引号 argv 传给 harness，不将任意 ref 输入拼入 shell 代码。所有必需门禁禁止 continue-on-error。报告在 always 路径上传，matrix 产物各有独立名称；普通 push/release 不通过新任务自动取消。依赖安装或 runner 被中止时可能尚无报告，必须查看 Actions job 状态，不能以“没有红色报告”当通过。[工作流语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。

## 建立远端后的接入

1. 确认仓库 URL、可见性与访问授权，再配置远端并推送；本轮不推送。
2. 在 Actions 启用工作流，先验证一次 PR/push/手动全树运行及失败日志上传。配置所需检查为两个 Python quality job，限制主分支写入/合并权限；根据平台方案可用性设置对应保护，不把仓库内 YAML 当成远端权限已生效。
3. 为 harness、CI、依赖基线、格式/提交协议建立审查责任；真实内核落地后逐项将 planned 变成真实 gate。性能/故障 runner 的网络、配额、对象前缀和清理预算先冻结，外部 PR 不直接运行有凭据或持久访问权的 self-hosted runner。
4. 明确证据长期保存位置与保留期。当前 Actions artifacts 14 天只是诊断保留；候选发布和性能基线到期前归档到授权的持久位置，不能只保留 URL/摘要。

## 后续 CD 接入合同

有可部署服务和明确目标环境后再实现：固定 source commit → 真实构建/测试 → 生成带版本/依赖与校验的不可变产物 → 完整发布门禁 → staging 部署/恢复 smoke → 用同一 digest 产物晋升生产。禁止在各环境重新构建不同字节却仍视作同一发布。

staging/production 通过独立的 GitHub Environment 绑定授权、环境配置和保护条件，按平台方案可用性设置 reviewer/分支限制；生产并发串行且不取消进行中的部署。部署身份仅在对应 job/environment 授予，云平台可用时采用短时身份联合，凭据不进入代码、tag 或日志。[GitHub 部署环境](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。

晋升前记录部署版本、产物 digest、数据/索引格式及迁移前提、兼容窗口、pin/进行中作业、备份点、健康与恢复断言。失败时保留日志并停止晋升；应用可回退到已知 digest，持久数据按具体迁移/对账方案恢复或向前修复。CD 重试必须有部署操作身份并检查已执行效果，不能靠盲目重跑假设撤销了业务副作用。

当前缺少远端 URL、构建/容器与 registry、目标运行环境、部署身份、健康/数据恢复合同及实际 release gate；这些是进入 CD 的实施前提，不阻止现有文档与 harness 开发。
