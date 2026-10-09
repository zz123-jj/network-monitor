import React, { useEffect, useState, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
const TimeChart = lazy(() => import("./TimeChart"));
const NAV = ["Overview", "Nodes", "Routes", "Events", "Settings"];
const RANGE = ["5m", "1h", "6h", "24h", "7d", "30d"];
const fmt = (n, digits = 1) =>
  n == null || !Number.isFinite(Number(n)) ? "—" : Number(n).toFixed(digits);
const clock = (ts) =>
  ts
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(ts * 1000))
    : "尚未探测";
const ago = (ts) =>
  !ts
    ? "尚无成功记录"
    : `${Math.max(0, Math.floor(Date.now() / 1000 - ts))}s ago`;
async function request(path, signal) {
  const res = await fetch("/api" + path, { signal });
  if (!res.ok) throw new Error(`请求失败 (${res.status})`);
  return res.json();
}
function usePoll(path, delay = 10000) {
  const [value, setValue] = useState(null),
    [error, setError] = useState(null),
    [busy, setBusy] = useState(true);
  useEffect(() => {
    let alive = true,
      timer;
    const controller = new AbortController();
    setValue(null);
    setBusy(true);
    async function update() {
      try {
        const data = await request(path, controller.signal);
        if (alive) {
          setValue(data);
          setError(null);
        }
      } catch (e) {
        if (alive && e.name !== "AbortError") setError(e.message);
      } finally {
        if (alive) {
          setBusy(false);
          timer = setTimeout(update, delay);
        }
      }
    }
    update();
    return () => {
      alive = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [path, delay]);
  return { value, error, busy };
}
function Icon({ type = "pulse", size = 18 }) {
  const paths = {
    pulse: "M2 12h5l3-8 5 16 3-8h4",
    grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    nodes: "M4 5h16v5H4z M4 14h16v5H4z",
    routes: "M5 4v16 M5 8h9 M14 8v8h5",
    events: "M12 3L2 21h20L12 3z M12 9v5 M12 17v1",
    settings: "M4 7h16 M4 17h16 M9 4v6 M16 14v6",
    arrow: "M5 12h14 M14 7l5 5-5 5",
    search: "M10 3a7 7 0 1 0 0 14a7 7 0 1 0 0-14 M15 15l6 6",
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[type] || paths.pulse} />
    </svg>
  );
}
function Status({ value }) {
  return (
    <span className={`status ${value}`}>
      <i />
      {(value || "unknown").toUpperCase()}
    </span>
  );
}
function Empty({ title = "尚无数据", children }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={30} />
      </div>
      <h3>{title}</h3>
      <p>{children || "首次探测完成后，这里会自动更新。"}</p>
    </div>
  );
}
function Banner({ children }) {
  return (
    <div className="banner" role="alert">
      {children}
    </div>
  );
}
function metric(n, key) {
  const c = n.checks || {};
  return {
    rtt: c.ping?.ping_avg_ms,
    loss: c.ping?.packet_loss_percent,
    jitter: c.ping?.jitter_ms,
    tcp: c.tcp?.ports
      ?.filter((p) => p.success)
      .reduce(
        (a, p) =>
          a == null ? p.tcp_connect_ms : Math.min(a, p.tcp_connect_ms),
        null,
      ),
    https: c.https?.https_total_ms,
  }[key];
}
function Metric({ label, value, unit = "ms", note }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <div>
        {fmt(value)}
        <small>{value == null ? "" : unit}</small>
      </div>
      {note && <p>{note}</p>}
    </div>
  );
}
function NodeCard({ node }) {
  return (
    <a className="node-card" href={`#/node/${encodeURIComponent(node.name)}`}>
      <div className="card-top">
        <span className="node-icon">
          <Icon type="nodes" />
        </span>
        <Status value={node.status} />
      </div>
      <h3>
        {node.name}
        <Icon type="arrow" size={16} />
      </h3>
      <p>{[node.location, node.region].filter(Boolean).join(", ")}</p>
      <code>{node.host}</code>
      <div className="card-primary">
        <Metric label="ROUND-TRIP TIME" value={metric(node, "rtt")} />
        <Metric label="PACKET LOSS" value={metric(node, "loss")} unit="%" />
      </div>
      <div className="card-secondary">
        {["jitter", "tcp", "https"].map((key) => (
          <div key={key}>
            <span>{key.toUpperCase()}</span>
            <strong>
              {fmt(metric(node, key))}
              <small> ms</small>
            </strong>
          </div>
        ))}
      </div>
      <footer>
        <span>Last success</span>
        <span>{ago(node.last_success)}</span>
      </footer>
    </a>
  );
}
function EventsList({ events, compact = false }) {
  if (!events?.length)
    return (
      <Empty title="暂无异常事件">连续探测达到阈值后，事件会出现在这里。</Empty>
    );
  return (
    <div className="event-list">
      {events.map((e) => (
        <div className="event" key={e.id}>
          <i className={`event-dot ${e.severity}`} />
          <time>{clock(e.timestamp)}</time>
          <a href={`#/node/${encodeURIComponent(e.node)}`}>{e.node}</a>
          <span className="event-message">{e.message}</span>
          {!compact && <span className="event-type">{e.type}</span>}
        </div>
      ))}
    </div>
  );
}
function Overview({ nodes, events }) {
  const active = nodes.filter((n) => n.enabled);
  const counts = Object.fromEntries(
    ["online", "warning", "offline"].map((s) => [
      s,
      active.filter((n) => n.status === s).length,
    ]),
  );
  const average = (key) => {
    const values = active.map((n) => metric(n, key)).filter((x) => x != null);
    return values.length
      ? values.reduce((a, b) => a + b, 0) / values.length
      : null;
  };
  return (
    <>
      <div className="page-title">
        <div className="eyebrow">NETWORK OBSERVABILITY</div>
        <h1>Overview</h1>
        <p>从国内观测点，持续了解每一条海外连接。</p>
      </div>
      <div className="global-stats">
        {[
          ["Total nodes", active.length, ""],
          ["Online", counts.online, "online"],
          ["Warning", counts.warning, "warning"],
          ["Offline", counts.offline, "offline"],
        ].map(([label, value, color]) => (
          <div key={label} className="stat">
            <span>
              {color && <i className={`dot ${color}`} />} {label}
            </span>
            <strong>{value.toString().padStart(2, "0")}</strong>
          </div>
        ))}
        <div className="stat">
          <span>Average RTT</span>
          <strong>
            {fmt(average("rtt"))}
            <small> ms</small>
          </strong>
        </div>
        <div className="stat">
          <span>Average loss</span>
          <strong>
            {fmt(average("loss"))}
            <small> %</small>
          </strong>
        </div>
      </div>
      <div className="section-heading">
        <h2>
          Monitored nodes <span>{active.length}</span>
        </h2>
        <span className="muted">主动探测 · 10 秒刷新</span>
      </div>
      {active.length ? (
        <div className="node-grid">
          {active.map((n) => (
            <NodeCard key={n.name} node={n} />
          ))}
        </div>
      ) : (
        <Empty title="添加你的第一个观测节点">
          编辑 config/nodes.yaml 填写 Tokyo VPS，保存后自动开始探测。
          <br />
          前往 Settings 查看配置方式。
        </Empty>
      )}
      <div className="section-heading">
        <h2>Recent events</h2>
        <a href="#/events">
          View all <Icon type="arrow" size={14} />
        </a>
      </div>
      <EventsList compact events={events?.slice(0, 5)} />
    </>
  );
}
function Nodes({ nodes }) {
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("all"),
    [region, setRegion] = useState("all"),
    [sort, setSort] = useState("name");
  const regions = [...new Set(nodes.map((n) => n.region))];
  const selected = nodes
    .filter(
      (n) =>
        `${n.name} ${n.host} ${n.provider} ${n.tags.join(" ")}`
          .toLowerCase()
          .includes(search.toLowerCase()) &&
        (status === "all" || n.status === status) &&
        (region === "all" || n.region === region),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : (metric(b, sort) ?? -1) - (metric(a, sort) ?? -1),
    );
  return (
    <>
      <div className="page-title">
        <div className="eyebrow">INVENTORY</div>
        <h1>Nodes</h1>
        <p>所有节点、端口与当前连接状态。</p>
      </div>
      <div className="filters">
        <label className="search">
          <Icon type="search" />
          <input
            aria-label="搜索节点"
            placeholder="Search nodes, IP, tags…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <select
          aria-label="状态筛选"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          {[
            "online",
            "warning",
            "offline",
            "pending",
            "unknown",
            "disabled",
          ].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="地区筛选"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
        >
          <option value="all">All regions</option>
          {regions.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <select
          aria-label="排序"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="name">Name A–Z</option>
          <option value="rtt">RTT · high first</option>
          <option value="loss">Loss · high first</option>
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {[
                "Node",
                "Region",
                "Status",
                "RTT",
                "Loss",
                "Jitter",
                "TCP",
                "HTTPS",
                "Last success",
              ].map((t) => (
                <th key={t}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {selected.map((n) => (
              <tr key={n.name}>
                <td>
                  <a href={`#/node/${encodeURIComponent(n.name)}`}>{n.name}</a>
                  <code>{n.host}</code>
                </td>
                <td>{n.region}</td>
                <td>
                  <Status value={n.status} />
                </td>
                {["rtt", "loss", "jitter", "tcp", "https"].map((k) => (
                  <td key={k}>
                    {fmt(metric(n, k))}
                    <small> {k === "loss" ? "%" : "ms"}</small>
                  </td>
                ))}
                <td className="muted">{ago(n.last_success)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!selected.length && <Empty title="没有匹配的节点" />}
      </div>
    </>
  );
}
function NodeDetail({ node }) {
  const [range, setRange] = useState("1h"),
    [end, setEnd] = useState(null);
  const path = node
    ? `/history?node=${encodeURIComponent(node.name)}&range=${range}${end ? `&end=${end}` : ""}`
    : "/history?node=";
  const history = usePoll(path, 30000);
  if (!node)
    return <Empty title="节点不存在">请检查节点配置或返回 Overview。</Empty>;
  const charts = [
    ["rtt", "RTT", "ms"],
    ["loss", "Packet loss", "%"],
    ["jitter", "Jitter", "ms"],
    ["tcp", "TCP connect", "ms"],
    ["https", "HTTPS total", "ms"],
    ["dns", "DNS resolution", "ms"],
    ["tls", "TLS handshake", "ms"],
    ["mtr", "MTR end-to-end", "ms"],
  ];
  return (
    <>
      <a className="back" href="#/overview">
        ← All nodes
      </a>
      <div className="page-title detail-title">
        <div>
          <div className="eyebrow">NODE DETAILS</div>
          <h1>{node.name}</h1>
          <p>
            {node.location}, {node.region} <code>{node.host}</code>
          </p>
        </div>
        <div>
          <Status value={node.status} />
          <p>Last probe: {clock(node.checks?.ping?.timestamp)}</p>
          <p>Last success: {ago(node.last_success)}</p>
        </div>
      </div>
      {Object.entries(node.checks || {})
        .filter(([, v]) => v.error)
        .map(([k, v]) => (
          <Banner key={k}>
            {k}: {v.error}
          </Banner>
        ))}
      <div className="detail-metrics">
        {["rtt", "loss", "jitter", "tcp", "https"].map((k) => (
          <Metric
            key={k}
            label={k.toUpperCase()}
            value={metric(node, k)}
            unit={k === "loss" ? "%" : "ms"}
          />
        ))}
      </div>
      {(node.tcp_ports.length > 0 || node.https_url) && (
        <div className="port-strip">
          {node.tcp_ports.map((p) => {
            const c = node.checks?.tcp?.ports?.find((v) => v.port === p);
            return (
              <span key={p}>
                :{p}{" "}
                <i
                  className={`dot ${c?.success ? "online" : c ? "offline" : "unknown"}`}
                />{" "}
                {fmt(c?.tcp_connect_ms)} ms
              </span>
            );
          })}
          {node.https_url && (
            <>
              <span>
                HTTP status{" "}
                <strong>{node.checks?.https?.https_status_code || "—"}</strong>
              </span>
              {[
                ["DNS", "https_dns_ms"],
                ["TCP", "https_connect_ms"],
                ["TLS", "https_tls_ms"],
                ["TTFB", "https_ttfb_ms"],
              ].map(([label, key]) => (
                <span key={key}>
                  HTTPS {label} {fmt(node.checks?.https?.[key])} ms
                </span>
              ))}
            </>
          )}
        </div>
      )}
      <div className="section-heading chart-controls">
        <div>
          <h2>Connection history</h2>
          <p className="muted">UTC+8 · 红色区域为 Offline · 缺失数据保留断点</p>
        </div>
        <div className="time-selector">
          {RANGE.map((r) => (
            <button
              key={r}
              className={range === r ? "active" : ""}
              onClick={() => {
                setRange(r);
                setEnd(null);
              }}
            >
              {r}
            </button>
          ))}
          <button
            title="查看前一个时间窗口"
            onClick={() =>
              setEnd(
                (end || Date.now() / 1000) -
                  {
                    "5m": 300,
                    "1h": 3600,
                    "6h": 21600,
                    "24h": 86400,
                    "7d": 604800,
                    "30d": 2592000,
                  }[range],
              )
            }
          >
            ←
          </button>
          <button onClick={() => setEnd(null)}>Live</button>
        </div>
      </div>
      {history.error && <Banner>历史数据暂不可用：{history.error}</Banner>}
      <div className="chart-grid">
        {charts.map(([key, label, unit], i) => (
          <section className="chart-card" key={key}>
            <header>
              <h3>{label}</h3>
              <span>{unit}</span>
            </header>
            <Suspense
              fallback={<div className="chart-loading">Loading chart…</div>}
            >
              <TimeChart
                series={history.value?.series[key] || []}
                status={history.value?.series.status || []}
                bounds={history.value}
                unit={unit}
                color={i === 1 ? "#cda75e" : i === 2 ? "#8d9fde" : "#68a8f8"}
              />
            </Suspense>
          </section>
        ))}
      </div>
      <p className="chart-note">
        Ctrl + 滚轮缩放 · 拖动图表或底部滑块平移 · TCP 每条曲线对应端口。MTR
        跳点不响应时，终点指标为空。
      </p>
      {node.description && <p className="muted">{node.description}</p>}
    </>
  );
}
function Routes({ nodes }) {
  const routes = usePoll("/routes", 30000);
  const [name, setName] = useState("");
  const selected = name || nodes.find((n) => n.enabled)?.name || "";
  const route = routes.value?.[selected];
  return (
    <>
      <div className="page-title">
        <div className="eyebrow">PATH INSPECTION</div>
        <h1>Routes</h1>
        <p>最新一次 MTR · 中间跳丢包不等于端到端丢包。</p>
      </div>
      <div className="filters">
        <select
          aria-label="路由节点"
          value={selected}
          onChange={(e) => setName(e.target.value)}
        >
          {nodes
            .filter((n) => n.enabled)
            .map((n) => (
              <option key={n.name}>{n.name}</option>
            ))}
        </select>
        <span className="muted">
          {route ? clock(route.timestamp) : "等待首次 MTR"}
        </span>
      </div>
      {routes.error && <Banner>{routes.error}</Banner>}
      {route?.error && <Banner>MTR: {route.error}</Banner>}
      {route?.hops?.length ? (
        <div className="route-panel">
          <div className="route-source">
            <i className="dot online" /> 国内观测点 <span>Source</span>
          </div>
          {route.hops.map((h, i) => (
            <div className="hop" key={h.hop}>
              <div className="hop-number">{h.hop}</div>
              <div className="hop-host">
                <strong>{h.ip || "* · No response"}</strong>
                <span>
                  {h.hostname ||
                    (i === route.hops.length - 1 && route.success
                      ? selected
                      : "")}
                </span>
              </div>
              <div>
                <span>AVG RTT</span>
                <strong>
                  {fmt(h.avg_ms)} <small>ms</small>
                </strong>
              </div>
              <div>
                <span>LOSS</span>
                <strong>
                  {fmt(h.loss_percent)} <small>%</small>
                </strong>
              </div>
              <div>
                <span>STDEV</span>
                <strong>
                  {fmt(h.jitter_ms)} <small>ms</small>
                </strong>
              </div>
            </div>
          ))}
          <p className="muted route-note">
            {route.success
              ? "已确认到达目标。"
              : "未确认到达目标；防火墙或 ICMP 限速可能隐藏跳点。"}{" "}
            数字模式关闭反向 DNS，减少查询和阻塞。
          </p>
        </div>
      ) : (
        <Empty title="等待路由探测">
          MTR 默认每 5 分钟执行一次，最长执行 45 秒。
        </Empty>
      )}
    </>
  );
}
function Events({ nodes }) {
  const [node, setNode] = useState(""),
    [type, setType] = useState("all"),
    [before, setBefore] = useState(null),
    [older, setOlder] = useState([]);
  const path = `/events?limit=100${node ? `&node=${encodeURIComponent(node)}` : ""}${before ? `&before=${before}` : ""}`;
  const events = usePoll(path, 15000);
  useEffect(() => {
    setBefore(null);
    setOlder([]);
  }, [node]);
  const all = [...older, ...(events.value || [])].filter(
    (e, i, arr) => arr.findIndex((v) => v.id === e.id) === i,
  );
  return (
    <>
      <div className="page-title">
        <div className="eyebrow">INCIDENT TIMELINE</div>
        <h1>Events</h1>
        <p>持续异常与恢复记录 · 连续观察防抖 · 重复异常冷却。</p>
      </div>
      <div className="filters">
        <select
          aria-label="事件节点"
          value={node}
          onChange={(e) => setNode(e.target.value)}
        >
          <option value="">All nodes</option>
          {nodes.map((n) => (
            <option key={n.name}>{n.name}</option>
          ))}
        </select>
        <select
          aria-label="事件类型"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="all">All events</option>
          {[
            "offline",
            "recovery",
            "high_latency",
            "packet_loss",
            "high_jitter",
          ].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <span className="muted">{all.length} loaded</span>
      </div>
      {events.error && <Banner>{events.error}</Banner>}
      <EventsList
        events={all.filter((e) => type === "all" || e.type === type)}
      />
      {events.value?.length === 100 && (
        <button
          className="load-more"
          onClick={() => {
            setOlder(all);
            setBefore(events.value.at(-1).id);
          }}
        >
          Load older events
        </button>
      )}
    </>
  );
}
function Settings({ data }) {
  const settings = data?.settings;
  return (
    <>
      <div className="page-title">
        <div className="eyebrow">OBSERVATION POINT</div>
        <h1>Settings</h1>
        <p>配置由服务器文件管理，保存后自动加载。</p>
      </div>
      <div className="settings-grid">
        <section className="settings-panel">
          <h2>Probe intervals</h2>
          {settings ? (
            Object.entries(settings.intervals).map(([k, v]) => (
              <div className="setting-row" key={k}>
                <span>{k.toUpperCase()}</span>
                <strong>{v}s</strong>
              </div>
            ))
          ) : (
            <p className="muted">等待服务返回配置。</p>
          )}
          <p className="muted">修改 config/nodes.yaml → settings.intervals</p>
        </section>
        <section className="settings-panel">
          <h2>Alert thresholds</h2>
          {settings &&
            ["rtt_ms", "loss_percent", "jitter_ms"].map((k) => (
              <div className="setting-row" key={k}>
                <span>{k.replaceAll("_", " ")}</span>
                <strong>
                  {settings.thresholds["warning_" + k]} /{" "}
                  {settings.thresholds["critical_" + k]}
                </strong>
              </div>
            ))}
          <p className="muted">
            Warning / Critical · {settings?.thresholds.debounce_samples}{" "}
            次连续观察 · {settings?.thresholds.cooldown_seconds}s 冷却
          </p>
        </section>
        <section className="settings-panel wide">
          <h2>Add a node</h2>
          <p className="muted">
            把以下结构加入 nodes 列表，替换 IP 和 URL。没有 HTTPS 服务时删除
            https_url。
          </p>
          <pre>{`nodes:\n  - name: Tokyo\n    host: 你的公网IP\n    region: Japan\n    location: Tokyo\n    tcp_ports: [22, 443]\n    https_url: https://你的域名/health\n    enabled: true\n    tags: [vless]`}</pre>
          <div className="setting-row">
            <span>Configuration reload</span>
            <strong>
              {data?.config_ok ? "Healthy · 10s" : "Unavailable / Invalid"}
            </strong>
          </div>
          <div className="setting-row">
            <span>Time zone</span>
            <strong>Asia/Shanghai · UTC+8</strong>
          </div>
          <p className="muted">
            Grafana 默认通过 SSH 隧道访问 localhost:3000。Prometheus、Exporter
            和 API 不映射公网端口。
          </p>
        </section>
      </div>
    </>
  );
}
function App() {
  const [route, setRoute] = useState(location.hash || "#/overview");
  useEffect(() => {
    const fn = () => setRoute(location.hash || "#/overview");
    addEventListener("hashchange", fn);
    return () => removeEventListener("hashchange", fn);
  }, []);
  const state = usePoll("/nodes");
  const events = usePoll("/events?limit=5", 15000);
  const nodes = (state.value?.nodes || []).map((n) =>
    state.error && n.enabled ? { ...n, status: "unknown", checks: {} } : n,
  );
  let [page, nodeName] = route.slice(2).split("/");
  try {
    nodeName = decodeURIComponent(nodeName || "");
  } catch {
    nodeName = "";
  }
  const node = nodes.find((n) => n.name === nodeName);
  const active = page === "node" ? "nodes" : page;
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/overview">
          <span className="brand-mark">
            <Icon />
          </span>
          Observatory<span className="brand-label">NETWORK</span>
        </a>
        <nav aria-label="主导航">
          {NAV.map((label, i) => (
            <a
              key={label}
              className={active === label.toLowerCase() ? "active" : ""}
              href={`#/${label.toLowerCase()}`}
            >
              <Icon
                type={["grid", "nodes", "routes", "events", "settings"][i]}
                size={15}
              />
              {label}
            </a>
          ))}
        </nav>
        <div className="observer-status">
          <i
            className={`dot ${state.error ? "offline" : state.value ? "online" : "unknown"}`}
          />
          <span>CN observer</span>
        </div>
      </header>
      <main>
        {state.error && (
          <Banner>观测服务连接中断：{state.error}。实时状态暂不可用。</Banner>
        )}
        {state.value && !state.value.config_ok && (
          <Banner>
            配置加载失败，继续使用最后有效配置：{state.value.config_error}
          </Banner>
        )}
        {state.value && !state.value.prometheus_ok && (
          <Banner>Prometheus 未成功抓取 Probe，历史数据可能中断。</Banner>
        )}
        {state.busy ? (
          <Empty title="正在连接观测服务…" />
        ) : page === "node" ? (
          <NodeDetail key={nodeName} node={node} />
        ) : page === "nodes" ? (
          <Nodes nodes={nodes} />
        ) : page === "routes" ? (
          <Routes nodes={nodes} />
        ) : page === "events" ? (
          <Events nodes={nodes} />
        ) : page === "settings" ? (
          <Settings data={state.value} />
        ) : (
          <Overview nodes={nodes} events={events.value} />
        )}
        <footer className="page-footer">
          <span>
            <Icon size={13} /> Network Observatory
          </span>
          <span>
            Asia/Shanghai · Live data ·{" "}
            {state.value ? clock(state.value.server_time) : "Connecting"}
          </span>
        </footer>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")).render(<App />);
