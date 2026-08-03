/**
 * Static dashboard for Hyderabad 22K gold tracker.
 * Loads JSON relative to this page so GitHub Pages project URLs work.
 */

const CHEAP_CODES = new Set(["D30_LOW", "NEAR_30D_LOW", "LOW_RANGE"]);
const DEAR_CODES = new Set(["D30_HIGH", "NEAR_30D_HIGH", "HIGH_RANGE"]);

function dataUrl(name) {
  const base = document.querySelector("script[src$='app.js']")?.getAttribute("src") || "./app.js";
  const dir = base.replace(/app\.js$/, "");
  return `${dir}data/${name}`;
}

function formatInr(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatMove(stats) {
  const ch = stats.daily_change;
  const pct = stats.daily_change_percent;
  if (ch == null || pct == null) return { text: "— ₹0 (0.00%)", dir: "flat" };
  if (stats.daily_direction === "up") {
    return { text: `▲ +₹${Math.abs(ch).toLocaleString("en-IN")} (+${pct.toFixed(2)}%)`, dir: "up" };
  }
  if (stats.daily_direction === "down") {
    return { text: `▼ -₹${Math.abs(ch).toLocaleString("en-IN")} (${pct.toFixed(2)}%)`, dir: "down" };
  }
  return { text: "— ₹0 (0.00%)", dir: "flat" };
}

function statusClass(code) {
  if (CHEAP_CODES.has(code)) return "status-cheap";
  if (DEAR_CODES.has(code)) return "status-dear";
  if (code === "NORMAL_RANGE") return "status-mid";
  return "status-unknown";
}

function parseDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function filterHistory(history, period) {
  if (period === "all") return history.slice();
  const days = Number(period);
  if (!history.length) return [];
  const end = parseDate(history[history.length - 1].date);
  const start = new Date(end);
  start.setDate(start.getDate() - (days - 1));
  return history.filter((r) => parseDate(r.date) >= start);
}

let chart;
let allHistory = [];
let currentStats = null;

function renderHero(stats) {
  document.getElementById("price").textContent = formatInr(stats.today_price);
  const move = formatMove(stats);
  const moveEl = document.getElementById("daily-move");
  moveEl.textContent = move.text;
  moveEl.className = `daily-move ${move.dir}`;

  const status = document.getElementById("status");
  status.className = `status ${statusClass(stats.classification)}`;
  document.getElementById("status-label").textContent = stats.classification_label || "—";

  const pos = stats.position_30d;
  document.getElementById("position").textContent = pos == null ? "—" : `${Math.round(pos)}%`;
  document.getElementById("low30").textContent = formatInr(stats.period_30d?.low);
  document.getElementById("high30").textContent = formatInr(stats.period_30d?.high);
  document.getElementById("avg30").textContent = formatInr(stats.period_30d?.average);

  const marker = document.getElementById("range-marker");
  const pct = pos == null ? 50 : Math.max(0, Math.min(100, pos));
  marker.style.left = `${pct}%`;

  const note = document.getElementById("history-note");
  if (stats.history_days != null && stats.history_days < 30) {
    note.hidden = false;
    note.textContent = `Only ${stats.history_days} day${stats.history_days === 1 ? "" : "s"} of history available so far.`;
  } else {
    note.hidden = true;
  }

  document.getElementById("stat-today").textContent = formatInr(stats.today_price);
  document.getElementById("stat-yesterday").textContent = formatInr(stats.yesterday_price);
  document.getElementById("stat-daily").textContent = move.text;
  document.getElementById("stat-30l").textContent = formatInr(stats.period_30d?.low);
  document.getElementById("stat-30h").textContent = formatInr(stats.period_30d?.high);
  document.getElementById("stat-30a").textContent = formatInr(stats.period_30d?.average);
  document.getElementById("stat-90l").textContent = formatInr(stats.period_90d?.low);
  document.getElementById("stat-90h").textContent = formatInr(stats.period_90d?.high);
  document.getElementById("stat-1yl").textContent = formatInr(stats.period_365d?.low);
  document.getElementById("stat-1yh").textContent = formatInr(stats.period_365d?.high);
  document.getElementById("last-updated").textContent = stats.last_updated || "—";
}

function renderChart(period) {
  const rows = filterHistory(allHistory, period);
  const labels = rows.map((r) => r.date);
  const prices = rows.map((r) => r.price);
  const low = prices.length ? Math.min(...prices) : null;
  const high = prices.length ? Math.max(...prices) : null;
  const current = prices.length ? prices[prices.length - 1] : null;

  const pointColors = prices.map((p, i) => {
    if (i === prices.length - 1) return "#7ec8ff";
    if (low != null && p === low) return "#3dba7a";
    if (high != null && p === high) return "#e25555";
    return "#c9a227";
  });
  const pointRadius = prices.map((p, i) => {
    if (i === prices.length - 1 || p === low || p === high) return 5;
    return 0;
  });

  const ctx = document.getElementById("price-chart");
  const data = {
    labels,
    datasets: [
      {
        label: "₹/g",
        data: prices,
        borderColor: "#c9a227",
        backgroundColor: "rgba(201, 162, 39, 0.12)",
        fill: true,
        tension: 0.25,
        pointBackgroundColor: pointColors,
        pointBorderColor: pointColors,
        pointRadius,
        pointHoverRadius: 6,
        borderWidth: 2,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => (items[0] ? items[0].label : ""),
          label: (item) => ` ${formatInr(item.parsed.y)} / gram`,
          afterBody: (items) => {
            if (!items.length) return [];
            const p = items[0].parsed.y;
            const tags = [];
            if (current != null && p === current && items[0].dataIndex === prices.length - 1) {
              tags.push("Current price");
            }
            if (low != null && p === low) tags.push("Period low");
            if (high != null && p === high) tags.push("Period high");
            return tags;
          },
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#9aab9f",
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 6,
          callback(value, index) {
            const label = this.getLabelForValue(value);
            if (!label) return "";
            const parts = String(label).split("-");
            return parts.length === 3 ? `${parts[2]}/${parts[1]}` : label;
          },
        },
        grid: { color: "rgba(243,240,231,0.06)" },
      },
      y: {
        ticks: {
          color: "#9aab9f",
          callback: (v) => "₹" + Number(v).toLocaleString("en-IN"),
        },
        grid: { color: "rgba(243,240,231,0.06)" },
      },
    },
  };

  if (chart) {
    chart.data = data;
    chart.options = options;
    chart.update();
  } else if (window.Chart) {
    chart = new Chart(ctx, { type: "line", data, options });
  }
}

async function loadJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return res.json();
}

async function init() {
  try {
    const [history, stats] = await Promise.all([
      loadJson(dataUrl("history.json")),
      loadJson(dataUrl("stats.json")),
    ]);
    allHistory = Array.isArray(history) ? history.slice().sort((a, b) => a.date.localeCompare(b.date)) : [];
    currentStats = stats;
    renderHero(stats);
    renderChart("30");
  } catch (err) {
    console.error(err);
    document.getElementById("status-label").textContent = "Failed to load data";
  }

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderChart(btn.dataset.period);
    });
  });
}

document.addEventListener("DOMContentLoaded", init);
