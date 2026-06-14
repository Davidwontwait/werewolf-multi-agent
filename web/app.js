const state = {
  data: null,
  selectedTarget: "",
  requestBusy: false,
  pollTimer: null,
};

const els = {
  statusLine: document.querySelector("#statusLine"),
  startBand: document.querySelector("#startBand"),
  playerSelect: document.querySelector("#playerSelect"),
  autoMode: document.querySelector("#autoMode"),
  startBtn: document.querySelector("#startBtn"),
  newGameBtn: document.querySelector("#newGameBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  playersGrid: document.querySelector("#playersGrid"),
  logList: document.querySelector("#logList"),
  actionBox: document.querySelector("#actionBox"),
  messagesBox: document.querySelector("#messagesBox"),
  busyOverlay: document.querySelector("#busyOverlay"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatText(value) {
  return escapeHtml(value).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
}

function setBusy(isBusy) {
  els.busyOverlay.hidden = !isBusy;
  document.querySelectorAll("button, textarea, select, input").forEach((el) => {
    el.disabled = isBusy;
  });
  if (!isBusy) {
    els.playerSelect.disabled = els.autoMode.checked;
  }
}

function updateBusy() {
  const data = state.data || {};
  const modelIsThinking = Boolean(data.job_running && !data.waiting_for_human && data.phase !== "ended");
  setBusy(modelIsThinking);
}

function schedulePoll() {
  const shouldPoll = Boolean(state.data?.job_running);
  if (shouldPoll && !state.pollTimer) {
    state.pollTimer = window.setInterval(loadState, 1600);
  }
  if (!shouldPoll && state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function api(path, options = {}) {
  state.requestBusy = true;
  updateBusy();
  try {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "请求失败");
    }
    state.data = data;
    state.selectedTarget = "";
    render();
    return data;
  } catch (err) {
    renderMessage(String(err.message || err));
  } finally {
    state.requestBusy = false;
    updateBusy();
  }
}

async function loadState() {
  try {
    const res = await fetch("/api/state");
    state.data = await res.json();
    render();
  } catch (err) {
    renderMessage(`状态刷新失败：${String(err.message || err)}`);
  }
}

function phaseLabel(data) {
  if (!data?.has_state) return `模型 ${data?.model || ""}`;
  if (data.job_error) return `后端任务出错 · ${data.model}`;
  if (data.phase === "ended") return `第 ${data.round} 轮 · ${data.winner}胜利 · ${data.model}`;
  if (data.waiting_for_human) return `第 ${data.round} 轮 · 等待你行动 · ${data.model}`;
  if (data.job_running) return `第 ${data.round} 轮 · 模型行动中 · ${data.model}`;
  return `第 ${data.round} 轮 · ${data.phase || "进行中"} · ${data.model}`;
}

function renderPlayers(data) {
  if (!data?.has_state) {
    els.playersGrid.innerHTML = `<div class="empty">暂无对局</div>`;
    return;
  }

  els.playersGrid.innerHTML = data.players.map((player) => {
    const classes = [
      "player-card",
      player.alive ? "alive" : "dead",
      player.is_human ? "human" : "",
    ].join(" ");
    return `
      <div class="${classes}">
        <div class="player-top">
          <span class="seat">${player.id}号${player.is_human ? " · 你" : ""}</span>
          <span class="role-mark">${player.role_emoji}</span>
        </div>
        <div class="role-name">${escapeHtml(player.role_cn)}</div>
        <div class="life-state ${player.alive ? "alive" : "dead"}">${player.alive ? "存活" : "死亡"}</div>
      </div>
    `;
  }).join("");
}

function logClass(item) {
  if (item.includes("白天") || item.includes("昨晚死亡")) return "day";
  if (item.includes("投票") || item.includes("出局")) return "vote";
  if (item.includes("号说")) return "speech";
  return "";
}

function renderLogs(data) {
  if (!data?.has_state || !data.public_log?.length) {
    els.logList.innerHTML = `<div class="empty">暂无公开记录</div>`;
    return;
  }

  els.logList.innerHTML = data.public_log.map((item) => {
    return `<div class="log-item ${logClass(item)}">${formatText(item)}</div>`;
  }).join("");
  els.logList.scrollTop = els.logList.scrollHeight;
}

function renderTargets(targets = [], allowZero = false) {
  const values = allowZero ? [0, ...targets] : targets;
  if (!values.length) return "";
  return `
    <div class="target-grid">
      ${values.map((target) => `<button type="button" data-target="${target}">${target}</button>`).join("")}
    </div>
  `;
}

function renderList(items = [], empty = "暂无") {
  if (!items.length) return `<div class="report-empty">${empty}</div>`;
  return items.map((item) => `<div class="report-line">${formatText(item)}</div>`).join("");
}

function renderFinalReport(report = {}) {
  const roleRows = (report.roles || []).map((role) => `
    <div class="role-row">
      <span>${role.id}号</span>
      <span>${role.role_emoji} ${escapeHtml(role.role_cn)}</span>
      <span class="${role.alive ? "alive" : "dead"}">${escapeHtml(role.status)}</span>
    </div>
  `).join("");

  return `
    <div class="final-report">
      <div class="report-section">
        <div class="report-title">身份表</div>
        <div class="role-table">${roleRows || '<div class="report-empty">暂无</div>'}</div>
      </div>
      <div class="report-section">
        <div class="report-title">关键事件</div>
        ${renderList(report.key_events)}
      </div>
      <div class="report-section">
        <div class="report-title">技能信息</div>
        ${renderList([...(report.seer_checks || []), ...(report.medicine_notes || [])])}
      </div>
      <div class="report-section">
        <div class="report-title">复盘</div>
        ${renderList(report.review)}
      </div>
      <div class="report-section">
        <div class="report-title">完整进程</div>
        ${renderList(report.timeline)}
      </div>
    </div>
  `;
}

function renderAction(data) {
  if (!data?.has_state) {
    els.actionBox.innerHTML = `<div class="empty">${data?.job_running ? "正在初始化对局" : "选择玩家编号后开始"}</div>`;
    return;
  }

  if (data.phase === "ended") {
    els.actionBox.innerHTML = `
      <div class="question">游戏结束：${escapeHtml(data.winner)}阵营胜利</div>
      ${renderFinalReport(data.final_report)}
    `;
    return;
  }

  if (!data.waiting_for_human) {
    els.actionBox.innerHTML = `<div class="empty">${data.observer_mode ? "观战中" : "模型行动中"}</div>`;
    return;
  }

  const action = data.pending_action;
  const validTargets = data.pending_metadata?.valid_targets || [];
  const allowZero = Boolean(data.pending_metadata?.allow_zero);
  const isSpeech = action === "speech";
  const isObserver = action === "observer_continue";

  if (isObserver) {
    els.actionBox.innerHTML = `
      <div class="question">${formatText(data.human_question)}</div>
      <button class="primary" id="observeBtn" type="button">进入观战</button>
    `;
    document.querySelector("#observeBtn").addEventListener("click", () => api("/api/observe", { method: "POST", body: "{}" }));
    return;
  }

  els.actionBox.innerHTML = `
    <div class="question">${formatText(data.human_question)}</div>
    ${renderTargets(validTargets, allowZero)}
    <textarea id="responseInput" placeholder="${isSpeech ? "输入发言" : "输入号码"}"></textarea>
    <button class="primary" id="submitBtn" type="button">提交</button>
  `;

  document.querySelectorAll("[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTarget = button.dataset.target;
      document.querySelector("#responseInput").value = state.selectedTarget;
    });
  });
  document.querySelector("#submitBtn").addEventListener("click", submitResponse);
}

function renderMessages(data) {
  const messages = [...(data?.messages || [])];
  if (data?.job_error) {
    messages.push(`后端任务出错：${data.job_error}`);
  }
  els.messagesBox.innerHTML = messages.slice(-8).map((message) => {
    return `<div class="message-item">${formatText(message)}</div>`;
  }).join("");
}

function renderMessage(message) {
  els.messagesBox.innerHTML = `<div class="message-item">${escapeHtml(message)}</div>`;
}

function render() {
  const data = state.data || {};
  els.statusLine.textContent = phaseLabel(data);
  els.startBand.hidden = data.has_state && data.phase !== "ended";
  els.playerSelect.disabled = els.autoMode.checked;
  renderPlayers(data);
  renderLogs(data);
  renderAction(data);
  renderMessages(data);
  schedulePoll();
  updateBusy();
}

async function startGame() {
  await api("/api/start", {
    method: "POST",
    body: JSON.stringify({
      player_id: els.playerSelect.value,
      auto_mode: els.autoMode.checked,
    }),
  });
}

async function submitResponse() {
  const input = document.querySelector("#responseInput");
  await api("/api/continue", {
    method: "POST",
    body: JSON.stringify({ response: input.value }),
  });
}

els.startBtn.addEventListener("click", startGame);
els.newGameBtn.addEventListener("click", () => {
  els.startBand.hidden = false;
  els.startBand.scrollIntoView({ behavior: "smooth", block: "start" });
});
els.refreshBtn.addEventListener("click", loadState);
els.autoMode.addEventListener("change", render);

loadState();
