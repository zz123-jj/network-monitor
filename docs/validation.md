# 实际验证记录

验证日期：2026-10-09，显示时区 Asia/Shanghai。初次验证宿主为 macOS ARM64，容器运行在 OrbStack 的 Linux Docker 环境；初次集成测试使用本地 TLS fixture。同日另完成实际 Ubuntu 24.04 amd64 大陆云服务器部署及真实海外节点验证，见下文。Ubuntu 安装脚本按 Docker 官方 Noble 仓库编写并通过 shell 语法检查，未在本机执行 apt/systemctl。

## 检查结果

| 检查 | 结果与依据 |
|---|---|
| Docker Compose | `docker compose config --quiet` 通过；六服务完整启动并均 healthy |
| Python | Python 3.12 语法解析通过；22 项 pytest 测试通过 |
| 前端 | 宿主与 Docker 内 `npm ci` / `npm run build` 通过 |
| YAML / JSON | Pydantic 节点配置、Prometheus/Blackbox YAML、Grafana provisioning、Dashboard JSON 结构检查通过 |
| Prometheus | 官方镜像 `/bin/promtool check config` 返回 SUCCESS；network-probe job 的 up=1 |
| Grafana | 自动 Dashboard UID network-monitor 存在；数据源 health OK；经 Grafana proxy 查询真实 network_ping_avg_ms 成功 |
| 同源 API | `/api/health` 返回 ok/prometheus/scraping 全部 true；GET 节点/历史/路线/事件正常 |
| ICMP | Docker 测试目标执行真实 ping，生成 RTT/avg/min/max/loss/jitter |
| TCP | 测试 TLS 端口连接成功；本地关闭端口失败，节点为 Warning 而非 Offline |
| HTTPS | 本地 TLS 服务、测试证书可信 CA（仅测试覆盖配置）验证通过；HTTP 200；DNS/TCP/TLS/TTFB/Total 有真实耗时 |
| MTR | 真实 mtr JSON，解析到达目标的数字 IP，route/avg/best/worst/loss/stdev/hops 与 metrics 可查询 |
| Blackbox | 测试 ICMP/TCP/HTTP job 均有指标；成功目标值 1，关闭 TCP 端口值 0 |
| Events | 临时降低 RTT 阈值触发真实样本告警，连续三轮才产生事件，同一异常每节点只记一次；恢复阈值后出现 Recovery |
| 配置热重载 | 写入无效 YAML 后继续监控原节点、config_ok=false；恢复完全相同旧文件后 config_ok=true；修复相关回退标记问题 |
| 持久化 | 停止/启动保留数据；冷备份成功；新项目空卷恢复后 SQLite 中四条测试事件完整；恢复栈六服务 healthy |
| 恢复保护 | 第二次向非空卷恢复被拒绝，没有覆盖已有历史 |
| 依赖检查 | 更新后 npm audit 与 pip-audit（含 Python transitive lock）均未报告已知漏洞；这不等于无未知漏洞 |
| 安全 | 无 shell=True，无任意目标/命令/PromQL API；所有命令有 timeout、取消时 kill/reap；capabilities/端口边界检查通过 |
| 1440px 桌面 | 实际 DOM width=1440，四列节点卡片，未出现整体横向溢出 |
| 1080p / 1440p | 实际 DOM 分别 1920×1080 / 2560×1440，main 最大宽度 1600，未出现整体横向溢出 |
| 390px 手机 | 图表宽度 336，页面无整体横向溢出；Nodes 表格宽约 732，限制在宽约 348 的可滚动容器内；搜索成功 |
| 浏览器错误 | 核验节点详情时控制台没有 error/warn |

## 测试目标与数据真实性

集成环境临时增加独立 `fixture` 容器，运行 tests/fixture.py 的标准库 HTTPS 服务器，探测 `fixture:9443`、真实 HEAD 请求和 ICMP/MTR；另一个 loopback 节点连接未监听的 TCP 端口。测试证书、私钥、节点覆盖 YAML 均在交付源码之外的临时工作目录，不在正式 Compose 中。

截图 [overview-desktop.jpg](overview-desktop.jpg) 与 [mobile-detail.jpg](mobile-detail.jpg) 是这些**真实本地测试样本**，不是海外网络数据。低 RTT 为同机容器之间实际结果；测试高延迟事件使用临时 0.01ms 阈值验证流程。没有编造时间序列、网页演示接口或预置公共目标。

本地集成测试数据已从默认运行栈清理；默认 nodes.yaml 恢复为空列表，首次部署必须填入自己的目标。默认六服务已重新自检。备份凭据、测试数据、node_modules、dist、缓存不进入交付压缩包。

## Code review 修复与结论

- `monitoring_internal` 保留出站能力；只 frontend 与 Grafana 发布端口，Grafana 默认 127.0.0.1。
- 修复 Nginx healthcheck 的 localhost IPv6 优先问题，使用 127.0.0.1；真实应用与容器健康一致。
- HTTP 503/证书错误有已连接证据时不误判整台节点 Offline；失败延迟 NaN → JSON null，不回填 0；状态未知不误宣告 Online/Offline，Probe 停止后历史通过 up/freshness 条件保留缺口。
- MTR 非目标末跳不能冒充端到端数据；路由 IP 不作为时序标签。
- 配置解析有目标/端口/URL/节点数边界，最后有效配置回退可恢复；只改变 description 等元数据不会清除持久告警状态。
- curl 禁用用户 rc、代理、URL glob 展开；不跟随重定向，启用 TLS 校验；采用 HEAD 限制数据流量。
- 子进程参数数组、超时、取消杀死并等待；节点故障独立处理，监督任务重启意外终止的探测。
- Snapshot 不重复携带完整 MTR hops，减小日常轮询体积，路线单独查询。
- API 查询最大约 601 点/曲线，范围白名单、并发限制、缓存上限；无动态 shell/host/PromQL 输入。
- 网络和 SQLite 用 UTC epoch，Web/Grafana 固定 UTC+8；持久卷、文件 provisioning、重启策略、日志轮转均已核对。
- Nginx 缓存策略通过 map 继承，避免 location 覆盖 add_header 导致 HTML 丢失 CSP/安全头。
- 前端连接失败时节点显示 Unknown；纯 HTTPS 节点不配置 TCP 时也能查看 HTTP code 与各阶段计时。
- 备份采用短暂停机，不复制运行中的不一致 WAL；恢复仅允许空卷。恢复 helper 仅在必要时增加 CHOWN/DAC_OVERRIDE/FOWNER，以正确还原数值 UID。

没有已知阻止当前范围部署的代码/配置问题。仍有明确范围限制：单观测点、MTR 最新路线、无 UDP/代理协议/带宽测试、Web 无内置登录/TLS、长时间曲线降采样、小批量 Ping 损耗分辨率较粗。见 README 第 16 节。

## 资源快照与未完成的环境验证

空节点配置下，本机一次 `docker stats --no-stream` 的内存约：Probe 39 MiB、Backend 40 MiB、Frontend 6 MiB、Blackbox 7 MiB、Prometheus 50 MiB、Grafana 265 MiB，合计约 **407 MiB**。此数字不是有大量节点/30 天历史时的保证值，也不是轻量云宿主内存总量。

初次本地测试未覆盖大陆云出站路径；后续实机验证补充如下。仍未执行 Ubuntu 的全新安装、30 天运行耐久或大量节点压力测试。新部署应运行 `bash scripts/test.sh`，再对自己的目标逐项验证。

## Ubuntu 24.04 大陆云实机验证

实机为 amd64、约 1.6 GiB RAM，Docker 与 Compose 已安装。服务器地址、节点 IP、账户凭据与本机 Compose override 不进入公共源码。

- 固定 Prometheus 3.13.4 / Blackbox 0.29.0 从官方 Quay 实际拉取；Grafana 13.2.2、Python 3.12.15、Node 22.23.3、Nginx 1.28.3 的 amd64 官方镜像由可信联网机器获取，经 SSH 传送并校验 SHA-256、RootFS 与 Config。
- 三个应用在 Ubuntu 完成生产构建；Python 语法、Pydantic 节点配置、Grafana provisioning、promtool 与 nginx -t 均通过。
- 六个服务最终均 healthy，未出现 OOM；restart policy 为 unless-stopped，Docker systemd 开机启动为 enabled。
- 实际海外节点产生 Ping/Loss/Jitter、TCP 443、21 跳 MTR、Prometheus 历史曲线和异常/恢复事件。节点网络告警与容器健康分别验证。
- Grafana 自动数据源健康 OK、经 Grafana 查询 network-probe up=1、已 provision 的 Dashboard UID 存在。关闭插件预装后启动不再等待远程插件下载。
- 通过可选 /grafana/ 反代访问登录页和认证查询；实际浏览器渲染 8 张详情图，1440px 页面及 390px 手机页面通过检查，无整体横向溢出或 JavaScript 运行错误。
- 实机离线镜像加载与 --no-build --pull never 启动通过，历史数据继续可查询，未删除数据卷；未执行整机重启。
- 修复 Ping 的 -c 与 -w 参数组合：丢包时原命令曾发送 19 包来收到 5 个回复，移除 -w 后实测严格发送 5 包；单次等待与外层 subprocess timeout 保留。

实机维护脚本使用本机镜像标签与路径；公共脚本保留相同离线流程，并检查 CPU 架构与项目名。公网 /grafana/ 为显式可选配置，默认 Grafana 仍绑定本机 3000。

## 可重复检查

```bash
bash scripts/init-env.sh
bash scripts/test.sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
PYTHONPATH=. .venv/bin/pytest -q tests
```

首次目标验证：保存真实 nodes.yaml 后等待 10–30 秒查看主指标，MTR 初次通常几十秒以内、之后 5 分钟周期。查看时间戳确实更新，而不是只看容器是否健康。
