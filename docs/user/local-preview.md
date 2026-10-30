# 本机预览安装物（本机有限验证）

仅已验macOS arm64、系统`/usr/bin/python3`>=3.9、已有Docker CLI和本地Unix Docker daemon运行Linux ARM64。engine是Linux ELF，不是Mac原生；需要预先存在固定runtime image，诊断不pull/下载/装包/启动daemon。Python仅stdlib安装与进程传输，不解析SQL/数据/发布语义；生产仍唯一Rust。数据准备、CLIP encoder/PyTorch reader独立可选，不入安装物。完整发行/MCP/安装普适性未认证。

构建者用scripts/build_preview.py显式engine与imageId产一份zipapp并输出SHA，禁止复制全target/model/env。消费者先按可信来源SHA外部校验，再运行包内安装逻辑；checksum证明字节一致，不是发行签名。

```sh
# 本机已持有一个明确SHA的预览包；先外部检查，勿执行未经核对来源的包。
printf '%s  %s\n' "$PREVIEW_SHA" "$PREVIEW_FILE" | shasum -a 256 -c -
/usr/bin/python3 "$PREVIEW_FILE" install --sha256 "$PREVIEW_SHA" --prefix "$NEW_PREFIX"
"$NEW_PREFIX/bin/guradb" capabilities
"$NEW_PREFIX/bin/guradb" doctor
"$NEW_PREFIX/bin/guradb" --data-root "$USER_DATA" query --config /data/corpus/config.json --sql 'SELECT doc_id,text FROM records ORDER BY doc_id LIMIT 5'
"$NEW_PREFIX/bin/guradb" --data-root "$USER_DATA" view status --store /data/store
```

prefix必须尚不存在（包括空目录/符号链接），父目录已存在；source/数据路径由用户显式data-root映射成/data，后面engine argv原样透传，未知格式/命令/错source仍由Rust拒绝，不吞退出码。只挂安装prefix内engine只读和这一用户root，cwd=/data，无checkout/target/主venv。环境PATH必须有已有docker或显式GURADB_DOCKER路径；默认local unix:///var/run/docker.sock，可显式本地GURADB_DOCKER_HOST，拒绝远端。安装物runtime用真实imageId sha256固定，--pull never/network none，缺镜像给可操作错误而不拉取。

只读capabilities校验安装文件摘要与host，显示来源/命令/格式/支持拒绝/预算，并明确runtime_checked=false；doctor另核实际系统Python、本地Docker daemon和image OS-arch；不扫描原ZIP/模型/全部用户输入、不执行query或发布store。安装物/manifest版本和ELF架构/摘要有界校验，坏/truncated/错架构/版本/existing sentinel拒绝；不写全局PATH/系统。升级装新prefix并存，回退显式调用旧prefix/bin/guradb，原安装与用户store不变。

单archive≤1GiB、本包新增owned≤2GiB。build≤120s/512MiB RSS、install≤60s+10s清理/streaming不拷全target；launcher≤20s工作+10s只清自身container，Rust仍原10s/源32MiB/decode64MiB/output2MiB/feature8MiB/2view128MiB描述1MiB，容器512MiB4CPU；不冒冷编译/发行性能。INT/TERM/timeout清自身未发布stage和自己container；安装完整目录原子提交后结果输出未知可用doctor公开对账，existing重试不覆盖，换新prefix并存。SIGKILL/断电完整矩阵未认证；不通过手改安装内部文件救成功。安装script在外部可信checksum核对后执行，内部重复校验避免误用；恶意替换整套manifest不是签名认证范围。
