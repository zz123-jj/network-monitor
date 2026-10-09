# 指标与 API

公共标签：node / region / host。TCP 追加 port（配置最多 8 个）；探测状态与时间戳追加 kind（ping/tcp/https/dns/mtr）。不使用错误文本、时间戳值、route IP 作为 label。

| 指标 | 定义 |
|---|---|
| network_node_up | Online/Warning=1，Offline=0，Pending/Unknown=NaN |
| network_node_status | Online=2，Warning=1，Offline=0，其他 NaN |
| network_ping_rtt_ms | 本轮最后成功回包 RTT |
| network_ping_avg_ms / min_ms / max_ms | 本轮成功回包的均值/最小/最大 |
| network_packet_loss_percent | 本轮 (发送-接收)/发送 ×100 |
| network_jitter_ms | 本轮相邻成功回包 RTT 绝对差平均值，少于两个回包为空 |
| network_tcp_connect_ms / network_tcp_success | 每端口成功建立 TCP 的耗时/是否成功 |
| network_dns_ms | 系统 getent resolver 耗时，不绕过缓存 |
| network_https_dns_ms | curl time_namelookup |
| network_https_connect_ms | curl time_connect − time_namelookup |
| network_https_tls_ms | curl time_appconnect − time_connect，无 TLS 时为空 |
| network_https_ttfb_ms | curl time_starttransfer，从请求开始到首字节 |
| network_https_total_ms | curl HEAD 总耗时 |
| network_https_status_code | HTTP code；未获得响应时 0 |
| network_mtr_avg_ms / best_ms / worst_ms | 确认到达目标后末跳统计，未到达为空 |
| network_mtr_loss_percent / jitter_ms / hops | 末跳损耗 / StDev / 报告 hop 数，最多 30 |
| network_probe_success | 按 kind 最近成功值，过期为 NaN |
| network_probe_timestamp_seconds | 按 kind 最近完成探测 Unix 时间 |
| network_last_success_timestamp_seconds | 最新一次可达性探测成功的 Unix 时间 |
| network_config_ok | 最后一次配置加载是否有效 |
| network_scheduler_timestamp_seconds | 监督任务 heartbeat |

均以 network_ 为完整前缀；表中使用 `/ min_ms / max_ms` 等缩写项对应相同基础前缀，例如 network_ping_min_ms。RTT、jitter、各阶段 timing 以毫秒计。失败不沿用旧延迟；没有配置的协议不创建对应序列。config 改动时移除当前不需要的 labels，历史按 retention 留存。

对外只读 API 经 Nginx 同源代理：

- `GET /api/health`：ok/prometheus/scraping。
- `GET /api/nodes`：配置元数据、当前状态、分协议 checks、settings 与配置健康。
- `GET /api/history?node=Tokyo&range=1h`：服务端固定指标查询；range=5m/1h/6h/24h/7d/30d，可选 end=UTC epoch。
- `GET /api/routes`：每个当前节点最近 MTR 的 JSON，包含 hops 与采样时间。
- `GET /api/events?node=Tokyo&limit=100&before=事件ID`：事件分页，limit 最大 500。

Probe 内部 `/metrics`、`/state`、`/routes`、`/events` 与 `/health` 不映射宿主端口。没有目标提交、命令执行、任意 PromQL 或配置更新端点。
