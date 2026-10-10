/* 前端逻辑：tab 切换、配置读写、诊断/扫描渲染、ECharts 图表 */
const $ = (id) => document.getElementById(id);

const DECISION_CN = { single: "单因", multiple: "多因", none: "无异常" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function round(v, n = 3) {
  return (v == null || isNaN(v)) ? "-" : Number(v).toFixed(n);
}

function fmtPct(v) {
  return (v == null || isNaN(v)) ? "-" : (v * 100).toFixed(1) + "%";
}

function renderMarkdown(md) {
  if (!md) return "";
  let html = "";
  try {
    html = marked.parse(md);
  } catch (e) {
    html = esc(md).replace(/\n/g, "<br>");
  }
  // 轻量清洗：去除脚本/iframe/事件属性（本地内部工具够用）
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(/\son\w+="[^"]*"/gi, "")
    .replace(/\son\w+='[^']*'/gi, "");
}

function setMsg(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = "msg " + (cls || "");
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

async function putJSON(url, body) {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------------------------------------------------------------- tab 切换
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "config") {
    const activeSub = document.querySelector(".subtab.active");
    switchSubtab(activeSub ? activeSub.dataset.subtab : "datasource");
  }
}

function switchSubtab(name) {
  document.querySelectorAll(".subtab").forEach((b) => b.classList.toggle("active", b.dataset.subtab === name));
  document.querySelectorAll(".subpanel").forEach((p) => p.classList.toggle("active", p.id === "config-" + name));
  if (name === "llm") loadLLMConfig();
  if (name === "datasource") loadDSConfig();
  if (name === "skills") loadSkills();
  if (name === "accounts") loadAccountsManager();
  if (name === "alert") loadAlertConfig();
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});
document.querySelectorAll(".subtab").forEach((btn) => {
  btn.addEventListener("click", () => switchSubtab(btn.dataset.subtab));
});

// ---------------------------------------------------------------- 账户列表
async function loadAccounts() {
  const res = await fetch("/api/accounts");
  const accs = await res.json();
  $("account-select").innerHTML = accs
    .map((a) => `<option value="${esc(a.advertiser_id)}">${esc(a.advertiser_name)}（${esc(a.advertiser_id)}）</option>`)
    .join("");
  renderAccountShortcuts(accs);
  $("scan-account-count").textContent = `共 ${accs.length} 个账户待扫描`;
}

function renderAccountShortcuts(accs) {
  const box = $("account-shortcuts");
  box.innerHTML = accs.map((a) => `
    <button class="account-chip" data-acc="${esc(a.advertiser_id)}">
      <span class="acc-name">${esc(a.advertiser_name)}</span>
      <span class="acc-id">${esc(a.advertiser_id)}</span>
    </button>`).join("");
  box.querySelectorAll(".account-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("account-select").value = btn.dataset.acc;
      $("btn-diagnose").click();
    });
  });
}

// ---------------------------------------------------------------- 诊断
$("btn-diagnose").addEventListener("click", async () => {
  const accountId = $("account-select").value;
  if (!accountId) return;
  $("diagnose-loading").classList.remove("hidden");
  $("diagnose-result").classList.add("hidden");
  try {
    const data = await postJSON("/api/diagnose", { account_id: accountId });
    $("diagnose-empty").classList.add("hidden");
    $("diagnose-result").classList.remove("hidden");  // 先显示，让图表容器有尺寸
    renderDiagnose(data);
  } catch (e) {
    alert("诊断失败：" + e.message);
  } finally {
    $("diagnose-loading").classList.add("hidden");
  }
});

function renderDiagnose(data) {
  lastDiagnosis = data;
  // 结论
  const topName = data.scores.length ? data.scores[0].name : "-";
  $("conclusion").dataset.decision = data.decision;
  $("conclusion").innerHTML =
    `<span class="badge ${data.decision}">${DECISION_CN[data.decision]}</span>` +
    `账户 <b>${esc(data.account_name)}</b>（${esc(data.account_id)}）` +
    (data.decision !== "none" ? ` · 首要根因：<b>${esc(topName)}</b>` : " · 未发现显著异常");

  renderFunnelChart($("funnel-chart"), data.evidence);
  renderScoresChart($("scores-chart"), data.scores);
  lastChartEls = { funnel: $("funnel-chart"), scores: $("scores-chart") };
  renderDrilldowns(data.drilldowns);
  $("report-text").innerHTML = renderMarkdown(data.report || "");
}

const chartRegistry = [];

function initChart(el) {
  const chart = echarts.getInstanceByDom(el) || echarts.init(el);
  chartRegistry.push(chart);
  return chart;
}

function renderFunnelChart(el, evidence) {
  const factors = evidence.map((e) => e.factor);
  const zs = evidence.map((e) => e.zscore);
  const chart = initChart(el);
  chart.setOption({
    tooltip: {
      trigger: "axis",
      formatter: (ps) => {
        const p = ps[0];
        const e = evidence[p.dataIndex];
        return `${e.factor}<br>偏离程度: ${e.zscore.toFixed(2)}<br>变化: ${fmtPct(e.pct_change)}`;
      },
    },
    grid: { left: 100, right: 60, top: 10, bottom:30 },
    xAxis: { type: "value", name: "偏离程度", splitLine: { lineStyle: { color: "#E2DED3" } } },
    yAxis: { type: "category", data: factors, inverse: true, axisLine: { show: false } },
    series: [{
      type: "bar",
      barWidth: "55%",
      data: zs.map((z) => ({
        value: z,
        itemStyle: { color: z < 0 ? "#B43A2A" : "#2E6E4E" },
      })),
      label: { show: true, position: "right", formatter: (p) => p.value.toFixed(2) },
    }],
  });
  chart.resize();
}

function renderScoresChart(el, scores) {
  const names = scores.map((s) => s.name).reverse();
  const vals = scores.map((s) => Number(s.score.toFixed(2))).reverse();
  const chart = initChart(el);
  chart.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: 130, right: 40, top: 10, bottom: 30 },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#E2DED3" } } },
    yAxis: { type: "category", data: names, axisLine: { show: false } },
    series: [{
      type: "bar",
      barWidth: "55%",
      data: vals,
      itemStyle: { color: "#2F4A5A" },
      label: { show: true, position: "right" },
    }],
  });
  chart.resize();
}

function renderDrilldowns(drilldowns) {
  const container = $("drilldowns");
  container.innerHTML = "";
  const cols = [
    ["creative_id", "素材ID"], ["creative_name", "素材名"],
    ["baseline", "基线"], ["recent", "近期"],
    ["delta", "变化"], ["denominator_share", "权重"],
    ["contribution", "贡献"],
  ];
  for (const [factor, rows] of Object.entries(drilldowns)) {
    if (!rows || !rows.length) continue;
    const head = cols.map(([k, label]) => `<th>${label}</th>`).join("");
    const body = rows.map((r) =>
      "<tr>" + cols.map(([k]) => `<td>${esc(round(r[k]))}</td>`).join("") + "</tr>"
    ).join("");
    container.innerHTML +=
      `<div class="drill-section"><h4>◆ ${esc(factor)}</h4>` +
      `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }
}

// ---------------------------------------------------------------- 扫描
$("btn-scan").addEventListener("click", async () => {
  $("scan-loading").classList.remove("hidden");
  $("scan-result").innerHTML = "";
  $("scan-summary").textContent = "";
  try {
    const data = await postJSON("/api/scan");
    $("scan-empty").classList.add("hidden");
    $("scan-summary").textContent = `扫描 ${data.scanned} 个账户，发现 ${data.anomalies.length} 个异常`;
    renderScan(data.anomalies);
  } catch (e) {
    alert("扫描失败：" + e.message);
  } finally {
    $("scan-loading").classList.add("hidden");
  }
});

function renderScan(anomalies) {
  const container = $("scan-result");
  if (!anomalies.length) {
    container.innerHTML = `<div class="card">✅ 未发现异常账户</div>`;
    return;
  }
  container.innerHTML = anomalies.map((a) => `
    <div class="scan-item">
      <div class="head">
        <span class="badge ${a.decision}">${DECISION_CN[a.decision]}</span>
        <span>${esc(a.account_name)}（${esc(a.account_id)}）</span>
        <span style="color:#6b7684;font-size:13px;font-weight:400">
          首要根因：${esc(a.scores.length ? a.scores[0].name : "-")}
        </span>
      </div>
      <div class="report" style="margin-top:10px">${renderMarkdown(a.report || "")}</div>
    </div>`).join("");
}

// ---------------------------------------------------------------- 数据源配置
function toggleDSMode() {
  const api = $("ds-mode").value === "真实 API";
  $("ds-synthetic").classList.toggle("hidden", api);
  $("ds-api").classList.toggle("hidden", !api);
}

async function loadDSConfig() {
  const c = await (await fetch("/api/config/datasource")).json();
  $("ds-platform").value = c.platform || "巨量千川";
  $("ds-mode").value = c.mode || "合成数据（演示）";
  $("ds-file").value = c.data_file || "";
  const api = c.api || {};
  $("api-appid").value = api.app_id || "";
  $("api-secret").value = api.secret || "";
  $("api-token").value = api.access_token || "";
  $("api-refresh").value = api.refresh_token || "";
  $("api-baseurl").value = api.base_url || "https://ad.oceanengine.com";
  $("api-days").value = api.days || 60;
  toggleDSMode();
}

$("ds-mode").addEventListener("change", toggleDSMode);

function collectDS() {
  return {
    platform: $("ds-platform").value,
    mode: $("ds-mode").value,
    data_file: $("ds-file").value,
    api: {
      app_id: $("api-appid").value,
      secret: $("api-secret").value,
      access_token: $("api-token").value,
      refresh_token: $("api-refresh").value,
      base_url: $("api-baseurl").value,
      days: parseInt($("api-days").value) || 60,
    },
  };
}

$("btn-save-ds").addEventListener("click", async () => {
  try {
    await putJSON("/api/config/datasource", collectDS());
    setMsg("ds-msg", "已保存", "ok");
  } catch (e) {
    setMsg("ds-msg", "保存失败：" + e.message, "err");
  }
});

$("btn-test-api").addEventListener("click", async () => {
  setMsg("api-msg", "测试中…", "");
  try {
    const r = await postJSON("/api/config/datasource/test", collectDS());
    setMsg("api-msg", r.ok ? `连接成功：${r.message}` : `连接失败：${r.message}`, r.ok ? "ok" : "err");
  } catch (e) {
    setMsg("api-msg", "测试失败：" + e.message, "err");
  }
});

// ---------------------------------------------------------------- 模型配置
async function loadLLMConfig() {
  const c = await (await fetch("/api/config/llm")).json();
  $("llm-provider").value = c.provider || "deepseek";
  $("llm-key").value = c.api_key || "";
  $("llm-model").value = c.model || "";
  $("llm-baseurl").value = c.base_url || "";
}

function collectLLM() {
  return {
    provider: $("llm-provider").value,
    api_key: $("llm-key").value,
    model: $("llm-model").value,
    base_url: $("llm-baseurl").value,
  };
}

$("btn-save-llm").addEventListener("click", async () => {
  try {
    await putJSON("/api/config/llm", collectLLM());
    setMsg("llm-msg", "已保存", "ok");
  } catch (e) {
    setMsg("llm-msg", "保存失败：" + e.message, "err");
  }
});

$("btn-test-llm").addEventListener("click", async () => {
  setMsg("llm-msg", "测试中…", "");
  try {
    await putJSON("/api/config/llm", collectLLM());  // 先保存，确保测的是当前 key
    const r = await postJSON("/api/config/llm/test");
    setMsg("llm-msg", r.ok ? `连接成功：${r.reply}` : `连接失败：${r.error}`, r.ok ? "ok" : "err");
  } catch (e) {
    setMsg("llm-msg", "测试失败：" + e.message, "err");
  }
});

// ---------------------------------------------------------------- 窗口缩放自适应
window.addEventListener("resize", () => {
  chartRegistry.forEach((c) => c.resize());
});

// ---------------------------------------------------------------- 对话状态
let chatChartSeq = 0;
let lastReportContent = null;
let pendingExport = false;
let sessions = [];
let currentSessionId = null;

// ---------------------------------------------------------------- 会话管理
function loadSessions() {
  return fetch("/api/sessions").then((r) => r.json()).then((d) => { sessions = d.sessions || []; })
    .catch(() => { sessions = []; });
}

function saveSessions() {
  fetch("/api/sessions", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessions }),
  }).catch(() => {});
}

function currentSession() {
  return sessions.find((s) => s.id === currentSessionId) || null;
}

function clearChat() {
  $("chat-history").innerHTML = "";
  lastReportContent = null;
  pendingExport = false;
}

function fmtTime(ts) {
  const d = new Date(ts);
  const diff = Date.now() - d;
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return Math.floor(diff / 60000) + " 分钟前";
  if (diff < 86400000) return Math.floor(diff / 3600000) + " 小时前";
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function renderSidebar() {
  const box = $("session-list");
  if (!sessions.length) {
    box.innerHTML = '<p class="hint">暂无历史对话</p>';
    return;
  }
  box.innerHTML = sessions.map((s) => `
    <div class="session-item ${s.id === currentSessionId ? "active" : ""}" data-sess="${esc(s.id)}">
      <span class="sess-title">${esc(s.title || "新对话")}</span>
      <span class="sess-time">${fmtTime(s.updated_at)}</span>
      <button class="sess-del" data-del="${esc(s.id)}" title="删除会话">×</button>
    </div>`).join("");
}

function deleteSession(id) {
  sessions = sessions.filter((s) => s.id !== id);
  saveSessions();
  if (id === currentSessionId) {
    if (sessions.length) switchSession(sessions[0].id);
    else newSession();
  } else {
    renderSidebar();
  }
}

function newSession() {
  const s = { id: "s" + Date.now(), title: "新对话", updated_at: Date.now(), messages: [] };
  sessions.unshift(s);
  currentSessionId = s.id;
  saveSessions();
  renderSidebar();
  clearChat();
  addWelcome();
}

function switchSession(id) {
  const s = sessions.find((x) => x.id === id);
  if (!s) return;
  currentSessionId = id;
  renderSidebar();
  clearChat();
  s.messages.forEach((m) => {
    if (m.role === "user") addChatMessage("user", m.content);
    else addChatMessage("agent", m.content);
    if (m.type === "diagnose") lastReportContent = m.content;
  });
  if (!s.messages.length) addWelcome();
  $("chat-history").scrollIntoView({ block: "end" });
}

function pushMessage(role, content, type, accountId) {
  const s = currentSession();
  if (!s) return;
  s.messages.push({ role, content, type: type || null, account_id: accountId || null });
  if (role === "user" && (!s.title || s.title === "新对话")) {
    s.title = content.slice(0, 20);
  }
  s.updated_at = Date.now();
  saveSessions();
  renderSidebar();
}

$("btn-new-chat").addEventListener("click", newSession);
$("session-list").addEventListener("click", (e) => {
  const del = e.target.dataset.del;
  if (del !== undefined) { deleteSession(del); return; }
  const id = e.target.closest(".session-item")?.dataset.sess;
  if (id) switchSession(id);
});

$("session-list").addEventListener("dblclick", (e) => {
  if (e.target.dataset.del !== undefined) return;
  const item = e.target.closest(".session-item");
  if (!item) return;
  const s = sessions.find((x) => x.id === item.dataset.sess);
  if (!s) return;
  const titleEl = item.querySelector(".sess-title");
  const input = document.createElement("input");
  input.className = "control sess-rename";
  input.value = s.title || "";
  titleEl.replaceWith(input);
  input.focus();
  input.select();
  let cancelled = false;
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") input.blur();
    if (ev.key === "Escape") { cancelled = true; input.blur(); }
  });
  input.addEventListener("blur", () => {
    if (!cancelled) {
      s.title = input.value.trim() || "新对话";
      saveSessions();
    }
    renderSidebar();
  });
});

// ---------------------------------------------------------------- 初始化
(async () => {
  loadAccounts();
  loadExportConfig();
  await loadSessions();
  if (sessions.length) {
    switchSession(sessions[0].id);
  } else {
    newSession();
  }
})();

function makeAvatar(role) {
  const a = document.createElement("div");
  a.className = "avatar " + role;
  a.textContent = role === "agent" ? "诊" : "我";
  return a;
}

function addChatMessage(role, content) {
  const el = document.createElement("div");
  el.className = "chat-msg " + role;
  el.appendChild(makeAvatar(role));
  const body = document.createElement("div");
  body.className = "msg-body";
  const bubble = document.createElement("div");
  if (role === "agent") {
    bubble.className = "bubble md";
    bubble.innerHTML = renderMarkdown(content);
  } else {
    bubble.className = "bubble";
    bubble.textContent = content;
  }
  body.appendChild(bubble);
  el.appendChild(body);
  $("chat-history").appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
}

function addThinking() {
  const el = document.createElement("div");
  el.className = "chat-msg agent";
  el.appendChild(makeAvatar("agent"));
  const body = document.createElement("div");
  body.className = "msg-body";
  const bubble = document.createElement("div");
  bubble.className = "bubble thinking";
  bubble.textContent = "正在思考";
  body.appendChild(bubble);
  el.appendChild(body);
  $("chat-history").appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

function appendChatExtras(el, content, meta) {
  if (!meta || meta.type !== "diagnose") return;
  if (meta.evidence && meta.evidence.length) {
    const charts = document.createElement("div");
    charts.className = "chat-charts";
    const fid = "funnel-c" + (++chatChartSeq);
    const sid = "scores-c" + (++chatChartSeq);
    charts.innerHTML = `<div id="${fid}" class="chat-chart"></div><div id="${sid}" class="chat-chart"></div>`;
    el.appendChild(charts);
    lastChartEls = { funnel: document.getElementById(fid), scores: document.getElementById(sid) };
    requestAnimationFrame(() => {
      renderFunnelChart(document.getElementById(fid), meta.evidence);
      renderScoresChart(document.getElementById(sid), meta.scores || []);
    });
  }
  if (meta.account_id) {
    const row = document.createElement("div");
    row.className = "chat-actions";
    const btnView = document.createElement("button");
    btnView.className = "btn btn-link";
    btnView.textContent = "查看素材下钻详情 →";
    btnView.dataset.jump = meta.account_id;
    row.appendChild(btnView);
    const btnExp = document.createElement("button");
    btnExp.className = "btn btn-link";
    btnExp.textContent = "导出报告";
    btnExp._export = { content, accountId: meta.account_id };
    row.appendChild(btnExp);
    el.appendChild(row);
  }
}

function typeAgentMessage(content, meta) {
  return new Promise((resolve) => {
    const el = document.createElement("div");
    el.className = "chat-msg agent";
    el.appendChild(makeAvatar("agent"));
    const body = document.createElement("div");
    body.className = "msg-body";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = "";
    body.appendChild(bubble);
    el.appendChild(body);
    $("chat-history").appendChild(el);
    let i = 0;
    const step = Math.max(2, Math.round(content.length / 120));
    const timer = setInterval(() => {
      i += step;
      if (i >= content.length) {
        bubble.className = "bubble md";
        bubble.innerHTML = renderMarkdown(content);
        clearInterval(timer);
        appendChatExtras(body, content, meta);
        el.scrollIntoView({ block: "end" });
        resolve();
      } else {
        bubble.textContent = content.slice(0, i);
        el.scrollIntoView({ block: "end" });
      }
    }, 10);
  });
}

function looksLikePath(s) {
  return /[A-Za-z]:[\\/]|\//.test(s.trim());
}

function extractFolder(msg) {
  const m = msg.match(/到\s*([A-Za-z]:[\\/][^\s，。]*|\/[^\s，。]*)/);
  if (m) return m[1];
  const m2 = msg.match(/([A-Za-z]:[\\/][^\s，。]*)/);
  return m2 ? m2[1] : null;
}

async function exportToFolder(folder, content) {
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return await postJSON("/api/export", {
    filename: `ROI诊断报告_${ts}.pdf`,
    content,
    dir: folder,
    format: "pdf",
    images: captureChartImages(),
  });
}

async function agentSay(content, meta) {
  await typeAgentMessage(content, meta);
  pushMessage("assistant", content, meta ? meta.type : null, meta ? meta.account_id : null);
  if (meta && meta.type === "diagnose") lastReportContent = content;
}

async function handleExport(folder) {
  if (!lastReportContent) {
    await agentSay("我还没找到可导出的诊断报告。请先让我诊断一次，比如问「为什么美妆旗舰店的ROI下降了？」", { type: "chat" });
    return;
  }
  try {
    const r = await exportToFolder(folder, lastReportContent);
    await agentSay("已导出到：" + r.path, { type: "chat" });
  } catch (e) {
    await agentSay("导出失败：" + e.message, { type: "chat" });
  }
}

async function sendChat() {
  const input = $("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  addChatMessage("user", msg);
  pushMessage("user", msg);

  // 导出命令
  if (/导出|export/i.test(msg)) {
    const folder = extractFolder(msg);
    if (folder) {
      await handleExport(folder);
    } else {
      pendingExport = true;
      await agentSay("好的，请问导出到哪个文件夹？直接回复完整路径，例如：D:\\reports", { type: "chat" });
    }
    return;
  }
  if (pendingExport && looksLikePath(msg)) {
    pendingExport = false;
    await handleExport(msg.trim());
    return;
  }

  // 正常请求
  const thinking = addThinking();
  let r;
  const s = currentSession();
  const history = s ? s.messages.slice(0, -1).map((m) => ({ role: m.role, content: m.content })) : [];
  try {
    r = await postJSON("/api/chat", { message: msg, history });
  } catch (e) {
    thinking.remove();
    addChatMessage("agent", "抱歉，出错了：" + e.message);
    pushMessage("assistant", "抱歉，出错了：" + e.message, "chat");
    return;
  }
  thinking.remove();
  await agentSay(r.content, r);
}

$("btn-send").addEventListener("click", sendChat);
$("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

$("chat-history").addEventListener("click", async (e) => {
  const jump = e.target.dataset.jump;
  if (jump) {
    switchTab("diagnose");
    $("account-select").value = jump;
    $("btn-diagnose").click();
    return;
  }
  const exp = e.target._export;
  if (exp) {
    try {
      await exportReport(exp.content, exp.accountId);
      e.target.textContent = "已导出 ✓";
      setTimeout(() => { e.target.textContent = "导出报告"; }, 2500);
    } catch (err) {
      e.target.textContent = "导出失败";
      setTimeout(() => { e.target.textContent = "导出报告"; }, 2500);
    }
  }
});

function addWelcome() {
  addChatMessage("agent",
    "你好，我是 ROI 诊断助手 👋\n\n你可以直接问我：\n\n- 「为什么美妆旗舰店的ROI下降了？」\n- 「扫描一下所有账户」\n- 「有哪些账户？」\n- 「导出报告」");
}

// ---------------------------------------------------------------- 导出
let lastDiagnosis = null;
let lastChartEls = { funnel: null, scores: null };

function captureChartImages() {
  const imgs = [];
  const entries = [["漏斗偏离", lastChartEls.funnel], ["根因打分", lastChartEls.scores]];
  for (const [label, el] of entries) {
    const chart = el && echarts.getInstanceByDom(el);
    if (chart) {
      try {
        const url = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
        imgs.push({ name: label + ".png", data: url.split(",")[1] });
      } catch (e) { /* 忽略 */ }
    }
  }
  return imgs;
}

async function loadExportConfig() {
  try {
    const c = await (await fetch("/api/config/export")).json();
    $("export-dir").value = c.dir || "";
  } catch (e) { /* 忽略 */ }
}

async function exportReport(content, accountId) {
  const dir = $("export-dir").value.trim();
  if (!dir) throw new Error("请先填写导出目录");
  await putJSON("/api/config/export", { dir });
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return await postJSON("/api/export", {
    filename: `ROI诊断_${accountId}_${ts}.pdf`,
    content,
    format: "pdf",
    images: captureChartImages(),
  });
}

$("btn-export").addEventListener("click", async () => {
  if (!lastDiagnosis) { setMsg("export-msg", "请先诊断一次", "err"); return; }
  try {
    const r = await exportReport(lastDiagnosis.report, lastDiagnosis.account_id);
    setMsg("export-msg", "已导出：" + r.path, "ok");
  } catch (e) { setMsg("export-msg", "导出失败：" + e.message, "err"); }
});

// ---------------------------------------------------------------- 技能配置
let skillsState = [];
let availableTools = [];
let skillsDirty = false;

function markDirty() {
  skillsDirty = true;
  $("btn-save-skills").textContent = "保存全部 ●未保存";
}
function markClean() {
  skillsDirty = false;
  $("btn-save-skills").textContent = "保存全部";
}

async function loadSkills() {
  const r = await (await fetch("/api/skills")).json();
  skillsState = r.skills || [];
  availableTools = r.tools || [];
  renderSkills();
  markClean();
}

function toolOptions(current) {
  const names = availableTools.map((t) => t.name);
  if (current && !names.includes(current)) names.unshift(current);
  return names.map((n) => `<option value="${esc(n)}" ${n === current ? "selected" : ""}>${esc(n)}</option>`).join("");
}

function renderSkills() {
  const container = $("skills-list");
  if (!skillsState.length) {
    container.innerHTML = '<div class="card">暂无技能，点「新增技能」或「重置为默认」。</div>';
    return;
  }
  container.innerHTML = skillsState.map((s, i) => `
    <div class="card skill-card" data-i="${i}">
      <div class="skill-head">
        <input class="control" data-i="${i}" data-k="name" value="${esc(s.name)}" placeholder="技能名">
        <button class="btn" data-del="${i}">删除</button>
      </div>
      <label>关联根因ID（可选，留空则靠「触发条件」自动匹配）</label>
      <input class="control" data-i="${i}" data-k="root_cause_id" value="${esc(s.root_cause_id)}">
      <label>触发条件（when：什么情况下用这个技能）</label>
      <input class="control" data-i="${i}" data-k="when" value="${esc(s.when)}">
      <label>调用工具（tool，只能选内置工具）</label>
      <select class="control" data-i="${i}" data-k="tool">${toolOptions(s.tool)}</select>
      <label>工具说明</label>
      <input class="control" data-i="${i}" data-k="tool_description" value="${esc(s.tool_description)}">
      <label>证实条件（confirm_if）</label>
      <input class="control" data-i="${i}" data-k="confirm_if" value="${esc(s.confirm_if)}">
      <label>排除条件（reject_if）</label>
      <input class="control" data-i="${i}" data-k="reject_if" value="${esc(s.reject_if)}">
    </div>`).join("");
}

function onSkillEdit(e) {
  const i = e.target.dataset.i, k = e.target.dataset.k;
  if (i === undefined || k === undefined) return;
  skillsState[+i][k] = e.target.value;
  markDirty();
}
$("skills-list").addEventListener("input", onSkillEdit);
$("skills-list").addEventListener("change", onSkillEdit);

$("skills-list").addEventListener("click", (e) => {
  const del = e.target.dataset.del;
  if (del !== undefined) { skillsState.splice(+del, 1); renderSkills(); markDirty(); }
});

$("btn-add-skill").addEventListener("click", () => {
  skillsState.push({ name: "新技能", root_cause_id: "", when: "", tool: availableTools[0]?.name || "", tool_description: "", confirm_if: "", reject_if: "" });
  renderSkills();
  markDirty();
});

$("btn-save-skills").addEventListener("click", async () => {
  try {
    await putJSON("/api/skills", { skills: skillsState });
    markClean();
    setMsg("skills-msg", "已保存", "ok");
  } catch (e) { setMsg("skills-msg", "保存失败：" + e.message, "err"); }
});

$("btn-reset-skills").addEventListener("click", async () => {
  const r = await postJSON("/api/skills/reset");
  skillsState = r.skills || [];
  renderSkills();
  markClean();
  setMsg("skills-msg", "已重置为默认", "ok");
});

$("btn-import-skills").addEventListener("click", () => {
  $("skills-json").value = "";
  $("import-box").classList.remove("hidden");
});

$("btn-export-skills").addEventListener("click", () => {
  $("skills-json").value = JSON.stringify(skillsState, null, 2);
  $("import-box").classList.remove("hidden");
});

$("btn-do-import").addEventListener("click", async () => {
  try {
    const parsed = JSON.parse($("skills-json").value);
    if (!Array.isArray(parsed)) throw new Error("必须是 JSON 数组");
    const r = await putJSON("/api/skills", { skills: parsed });
    skillsState = r.skills || [];
    renderSkills();
    $("import-box").classList.add("hidden");
    markClean();
    setMsg("skills-msg", "已导入", "ok");
  } catch (e) { setMsg("skills-msg", "导入失败：" + e.message, "err"); }
});

$("btn-cancel-import").addEventListener("click", () => {
  $("import-box").classList.add("hidden");
});

// ---------------------------------------------------------------- 账户管理
let accountsState = [];

async function loadAccountsManager() {
  const accs = await (await fetch("/api/accounts")).json();
  accountsState = accs || [];
  renderAccounts();
}

function renderAccounts() {
  const container = $("accounts-list");
  if (!accountsState.length) {
    container.innerHTML = '<p class="hint">暂无账户，点「新增账户」添加。</p>';
    return;
  }
  container.innerHTML = accountsState.map((a, i) => `
    <div class="account-row">
      <input class="control" data-i="${i}" data-k="advertiser_id" value="${esc(a.advertiser_id)}" placeholder="广告主ID">
      <input class="control" data-i="${i}" data-k="advertiser_name" value="${esc(a.advertiser_name)}" placeholder="店铺名称">
      <button class="btn" data-del="${i}">删除</button>
    </div>`).join("");
}

$("accounts-list").addEventListener("input", (e) => {
  const i = e.target.dataset.i, k = e.target.dataset.k;
  if (i === undefined || k === undefined) return;
  accountsState[+i][k] = e.target.value;
});

$("accounts-list").addEventListener("click", (e) => {
  const del = e.target.dataset.del;
  if (del !== undefined) { accountsState.splice(+del, 1); renderAccounts(); }
});

$("btn-add-account").addEventListener("click", () => {
  accountsState.push({ advertiser_id: "", advertiser_name: "" });
  renderAccounts();
});

$("btn-save-accounts").addEventListener("click", async () => {
  try {
    await putJSON("/api/accounts", { accounts: accountsState });
    loadAccounts();  // 刷新诊断页账户下拉
    setMsg("accounts-msg", "已保存", "ok");
  } catch (e) { setMsg("accounts-msg", "保存失败：" + e.message, "err"); }
});

// ---------------------------------------------------------------- 告警配置
let alertTargets = [];
const ALERT_CHANNELS = { feishu: "飞书", dingtalk: "钉钉", wecom: "企业微信" };

async function loadAlertConfig() {
  const c = await (await fetch("/api/config/alert")).json();
  $("alert-interval").value = c.interval_hours ?? 0;
  alertTargets = c.targets || [];
  renderAlertTargets();
}

function renderAlertTargets() {
  const box = $("alert-targets");
  if (!alertTargets.length) {
    box.innerHTML = '<p class="hint">暂无推送目标，点「新增推送目标」添加。</p>';
    return;
  }
  box.innerHTML = alertTargets.map((t, i) => {
    const chOpts = Object.entries(ALERT_CHANNELS)
      .map(([v, label]) => `<option value="${v}" ${t.channel === v ? "selected" : ""}>${label}</option>`).join("");
    return `
    <div class="alert-target">
      <div class="alert-target-row">
        <input class="control" data-i="${i}" data-k="name" value="${esc(t.name)}" placeholder="群名称（如：投放运营群）">
        <select class="control" data-i="${i}" data-k="channel">${chOpts}</select>
        <label class="enabled"><input type="checkbox" data-i="${i}" data-k="enabled" ${t.enabled !== false ? "checked" : ""}> 启用</label>
        <button class="btn" data-test="${i}">测试</button>
        <button class="btn" data-del="${i}">删除</button>
      </div>
      <input class="control" data-i="${i}" data-k="webhook_url" value="${esc(t.webhook_url)}" placeholder="webhook 地址，如 https://open.feishu.cn/open-apis/bot/v2/hook/xxxx">
    </div>`;
  }).join("");
}

function onAlertTargetEdit(e) {
  const i = e.target.dataset.i, k = e.target.dataset.k;
  if (i === undefined || k === undefined) return;
  if (k === "enabled") alertTargets[+i][k] = e.target.checked;
  else alertTargets[+i][k] = e.target.value;
}
$("alert-targets").addEventListener("input", onAlertTargetEdit);
$("alert-targets").addEventListener("change", onAlertTargetEdit);

$("alert-targets").addEventListener("click", async (e) => {
  const del = e.target.dataset.del;
  if (del !== undefined) { alertTargets.splice(+del, 1); renderAlertTargets(); return; }
  const ti = e.target.dataset.test;
  if (ti !== undefined) {
    setMsg("alert-msg", "测试中…", "");
    try {
      const r = await postJSON("/api/config/alert/test", { target: alertTargets[+ti] });
      setMsg("alert-msg", r.message, r.ok ? "ok" : "err");
    } catch (err) { setMsg("alert-msg", "测试失败：" + err.message, "err"); }
  }
});

$("btn-add-target").addEventListener("click", () => {
  alertTargets.push({ name: "", channel: "feishu", webhook_url: "", enabled: true });
  renderAlertTargets();
});

$("btn-save-alert").addEventListener("click", async () => {
  try {
    await putJSON("/api/config/alert", {
      targets: alertTargets,
      interval_hours: parseFloat($("alert-interval").value) || 0,
    });
    setMsg("alert-msg", "已保存", "ok");
  } catch (e) { setMsg("alert-msg", "保存失败：" + e.message, "err"); }
});
