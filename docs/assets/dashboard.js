/* KavionLens360 interactive dashboard: client-side slicing of a pre-aggregated cube. */
(() => {
  "use strict";

  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const SEG_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
  const TIER_VARS = { A: "--tierA", B: "--tierB", C: "--tierC", Watch: "--tierW" };
  const fmtInt = new Intl.NumberFormat("en-IN");
  const fmt1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });
  const pct = (x) => (isFinite(x) ? fmt1.format(100 * x) + "%" : "–");
  const inr = (x) => {
    if (!isFinite(x)) return "–";
    const a = Math.abs(x);
    if (a >= 1e7) return "₹" + fmt1.format(x / 1e7) + " Cr";
    if (a >= 1e5) return "₹" + fmt1.format(x / 1e5) + " L";
    return "₹" + fmtInt.format(Math.round(x));
  };
  const short = (x) => (Math.abs(x) >= 1e7 ? fmt1.format(x / 1e7) + " Cr" : Math.abs(x) >= 1e5 ? fmt1.format(x / 1e5) + " L" : Math.abs(x) >= 1e3 ? fmt1.format(x / 1e3) + "K" : fmtInt.format(x));

  let DATA, M, DIMS, state, charts = {};
  const FILTERS = [
    ["segment", "Segment"], ["age_group", "Age group"], ["gender", "Gender"],
    ["city", "City"], ["tier", "Tier"], ["evidence", "Evidence"],
  ];
  const DIM_ORDER = ["segment", "age_group", "gender", "city", "tier", "evidence"];

  // ------------------------------------------------------------------ data helpers
  function rows(except) {
    return DATA.cube.rows.filter((r) =>
      DIM_ORDER.every((d, i) => d === except || state[d] === "All" || DIMS[d][r[i]] === state[d]));
  }
  function total(rs, m) { const j = M[m]; let s = 0; for (const r of rs) s += r[j]; return s; }
  function by(rs, dim, measures) {
    const i = DIM_ORDER.indexOf(dim), out = DIMS[dim].map(() => Object.fromEntries(measures.map((m) => [m, 0])));
    for (const r of rs) for (const m of measures) out[r[i]][m] += r[M[m]];
    return out;
  }
  const segColor = (name) => css(SEG_VARS[DIMS.segment.indexOf(name) % SEG_VARS.length]);

  // ------------------------------------------------------------------ chart helpers
  function baseOptions(extra = {}) {
    const ink2 = css("--ink-2"), grid = css("--grid");
    return Object.assign({
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: css("--ink-2"),
          borderColor: css("--axis"), borderWidth: 1, padding: 10, cornerRadius: 8, displayColors: true, boxPadding: 4,
        },
      },
      scales: {
        x: { grid: { color: grid, drawTicks: false }, border: { color: css("--axis") }, ticks: { color: ink2, font: { size: 11 } } },
        y: { grid: { color: grid, drawTicks: false }, border: { display: false }, ticks: { color: ink2, font: { size: 11 } } },
      },
    }, extra);
  }
  function draw(id, config, table) {
    if (charts[id]) charts[id].destroy();
    const canvas = document.querySelector(`#${id} canvas`);
    charts[id] = new Chart(canvas, config);
    if (table) renderTable(document.querySelector(`#${id} .tableview`), table.head, table.rows);
  }
  function renderTable(el, head, body) {
    if (!el) return;
    el.innerHTML = `<div class="table-wrap"><table><thead><tr>${head.map((h, i) => `<th class="${i ? "num" : ""}">${h}</th>`).join("")}</tr></thead><tbody>${
      body.map((r) => `<tr>${r.map((c, i) => `<td class="${i ? "num" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function legend(id, items) {
    const el = document.querySelector(`#${id} .legend`);
    if (el) el.innerHTML = items.map(([label, color]) => `<span><i class="swatch" style="background:${color}"></i>${label}</span>`).join("");
  }
  const bar = (color) => ({ backgroundColor: color, borderRadius: 4, borderSkipped: "start", maxBarThickness: 28, categoryPercentage: 0.8, barPercentage: 0.9 });

  // ------------------------------------------------------------------ KPIs
  function kpis(el, items) {
    document.getElementById(el).innerHTML = items.map(([label, value, sub]) =>
      `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`).join("");
  }

  // ------------------------------------------------------------------ pages
  function renderExecutive() {
    const rs = rows();
    const cust = total(rs, "customers"), val = total(rs, "value"), tx = total(rs, "txns");
    kpis("kpi-exec", [
      ["Customers", fmtInt.format(cust), "distinct CustomerIDs"],
      ["Transaction value", inr(val), `${fmtInt.format(tx)} transactions`],
      ["Avg transaction", inr(val / tx), "value ÷ transactions"],
      ["Avg balance", inr(total(rs, "bal_sum") / total(rs, "bal_n")), "mean; heavily skewed"],
      ["Active rate", pct(total(rs, "active") / cust), "seen in last 15 days"],
      ["High-value", fmtInt.format(total(rs, "high_value")), pct(total(rs, "high_value") / cust) + " of customers"],
    ]);
    // age x gender
    const ai = DIM_ORDER.indexOf("age_group"), gi = DIM_ORDER.indexOf("gender");
    const genders = ["F", "M"], gcol = { F: css("--s1"), M: css("--s2") };
    const grid = DIMS.age_group.map(() => ({ F: 0, M: 0, Unknown: 0 }));
    for (const r of rs) grid[r[ai]][DIMS.gender[r[gi]]] += r[M.customers];
    draw("c-agegender", {
      type: "bar",
      data: { labels: DIMS.age_group, datasets: genders.map((g) => ({ label: g === "F" ? "Female" : "Male", data: grid.map((x) => x[g]), ...bar(gcol[g]) })) },
      options: baseOptions({ scales: { x: { grid: { display: false }, ticks: { color: css("--ink-2") } }, y: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") }, border: { display: false } } } }),
    }, { head: ["Age group", "Female", "Male", "Unknown gender"], rows: DIMS.age_group.map((a, i) => [a, fmtInt.format(grid[i].F), fmtInt.format(grid[i].M), fmtInt.format(grid[i].Unknown)]) });
    legend("c-agegender", [["Female", gcol.F], ["Male", gcol.M]]);

    // trend (city slicer only)
    const city = state.city === "All" ? null : state.city;
    const series = DATA.trend.series, dates = DATA.trend.dates;
    const tx2 = dates.map((_, i) => city ? (series[city] ? series[city].txns[i] : 0) : Object.values(series).reduce((s, v) => s + v.txns[i], 0));
    draw("c-trend", {
      type: "line",
      data: { labels: dates.map((d) => d.slice(5)), datasets: [{ label: "Transactions", data: tx2, borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25 }] },
      options: baseOptions({ interaction: { mode: "index", intersect: false }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, color: css("--ink-2") } }, y: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") }, border: { display: false } } } }),
    }, { head: ["Date", "Transactions"], rows: dates.map((d, i) => [d, fmtInt.format(tx2[i])]) });
    document.querySelector("#c-trend .q").textContent = city ? `Daily transactions in ${city} (responds to the City filter only)` : "Daily transactions, all cities (responds to the City filter only)";

    // top cities
    const bc = by(rows("city"), "city", ["value", "customers"]).map((v, i) => ({ city: DIMS.city[i], ...v }))
      .filter((c) => c.city !== "Other cities" && c.city !== "Unknown").sort((a, b) => b.value - a.value).slice(0, 12);
    draw("c-cities", {
      type: "bar",
      data: { labels: bc.map((c) => c.city), datasets: [{ label: "Transaction value", data: bc.map((c) => c.value), ...bar(bc.map((c) => state.city === "All" || state.city === c.city ? css("--s1") : css("--axis"))) }] },
      options: baseOptions({ indexAxis: "y", plugins: { legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip, callbacks: { label: (c) => " " + inr(c.raw) } } }, scales: { x: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") } }, y: { grid: { display: false }, ticks: { color: css("--ink-2") } } } }),
    }, { head: ["City", "Transaction value", "Customers"], rows: bc.map((c) => [c.city, inr(c.value), fmtInt.format(c.customers)]) });

    // segments
    const bs = by(rows("segment"), "segment", ["customers"]);
    draw("c-segdist", {
      type: "bar",
      data: { labels: DIMS.segment, datasets: [{ label: "Customers", data: bs.map((x) => x.customers), ...bar(DIMS.segment.map((s) => state.segment === "All" || state.segment === s ? segColor(s) : css("--axis"))) }] },
      options: baseOptions({ indexAxis: "y", scales: { x: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") } }, y: { grid: { display: false }, ticks: { color: css("--ink-2") } } } }),
    }, { head: ["Segment", "Customers"], rows: DIMS.segment.map((s, i) => [s, fmtInt.format(bs[i].customers)]) });
  }

  function renderSegments() {
    const rs = rows("segment");
    const all = rows();
    const cust = total(all, "customers");
    const segAll = by(rs, "segment", ["customers", "value", "txns", "bal_sum", "bal_n", "active", "high_value", "any_signal"]);
    const tc = segAll.reduce((s, x) => s + x.customers, 0), tv = segAll.reduce((s, x) => s + x.value, 0);
    kpis("kpi-seg", [
      ["Customers in selection", fmtInt.format(cust), state.segment === "All" ? "all segments" : state.segment],
      ["Share of customers", pct(cust / tc), "within other filters"],
      ["Share of value", pct(total(all, "value") / tv), "within other filters"],
      ["Txns per customer", fmt1.format(total(all, "txns") / cust), "46-day window"],
    ]);
    draw("c-sizevalue", {
      type: "bar",
      data: { labels: DIMS.segment, datasets: [
        { label: "% of customers", data: segAll.map((x) => 100 * x.customers / tc), ...bar(css("--s1")) },
        { label: "% of value", data: segAll.map((x) => 100 * x.value / tv), ...bar(css("--s2")) }] },
      options: baseOptions({ plugins: { legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip, callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt1.format(c.raw)}%` } } }, scales: { x: { grid: { display: false }, ticks: { color: css("--ink-2"), autoSkip: false, maxRotation: 0, callback(v) { return this.getLabelForValue(v).split(" ").reduce((a, w) => { const l = a[a.length - 1]; if (l && (l + " " + w).length <= 14) a[a.length - 1] = l + " " + w; else a.push(w); return a; }, []); } } }, y: { ticks: { callback: (v) => v + "%", color: css("--ink-2") }, grid: { color: css("--grid") }, border: { display: false } } } }),
    }, { head: ["Segment", "% of customers", "% of value"], rows: DIMS.segment.map((s, i) => [s, fmt1.format(100 * segAll[i].customers / tc) + "%", fmt1.format(100 * segAll[i].value / tv) + "%"]) });
    legend("c-sizevalue", [["% of customers", css("--s1")], ["% of value", css("--s2")]]);

    const prof = document.getElementById("t-profile");
    prof.innerHTML = `<table><thead><tr><th>Segment</th><th class="num">Customers</th><th class="num">Avg txn</th><th class="num">Mean balance</th><th class="num">Txns / cust</th><th class="num">Active</th><th class="num">High-value</th><th class="num">With signal</th></tr></thead><tbody>${
      DIMS.segment.map((s, i) => { const x = segAll[i]; return `<tr><td><i class="swatch" style="background:${segColor(s)}"></i>${s}</td><td class="num">${fmtInt.format(x.customers)}</td><td class="num">${inr(x.value / x.txns)}</td><td class="num">${inr(x.bal_sum / x.bal_n)}</td><td class="num">${fmt1.format(x.txns / x.customers)}</td><td class="num">${pct(x.active / x.customers)}</td><td class="num">${pct(x.high_value / x.customers)}</td><td class="num">${pct(x.any_signal / x.customers)}</td></tr>`; }).join("")}</tbody></table>`;

    // age mix (100% stacked by segment)
    const si = DIM_ORDER.indexOf("segment"), ai = DIM_ORDER.indexOf("age_group");
    const mix = DIMS.segment.map(() => DIMS.age_group.map(() => 0));
    for (const r of rows("segment")) mix[r[si]][r[ai]] += r[M.customers];
    const ramp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#104281", css("--axis")];
    draw("c-agemix", {
      type: "bar",
      data: { labels: DIMS.segment, datasets: DIMS.age_group.map((a, j) => ({ label: a, data: mix.map((row) => 100 * row[j] / (row.reduce((s, v) => s + v, 0) || 1)), backgroundColor: ramp[j], borderColor: css("--surface"), borderWidth: { right: 2 }, borderSkipped: false, maxBarThickness: 26 })) },
      options: baseOptions({ indexAxis: "y", plugins: { legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip, callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt1.format(c.raw)}%` } } }, scales: { x: { stacked: true, max: 100, ticks: { callback: (v) => v + "%", color: css("--ink-2") }, grid: { color: css("--grid") } }, y: { stacked: true, grid: { display: false }, ticks: { color: css("--ink-2") } } } }),
    }, { head: ["Segment", ...DIMS.age_group], rows: DIMS.segment.map((s, i) => [s, ...mix[i].map((v) => fmtInt.format(v))]) });
    legend("c-agemix", DIMS.age_group.map((a, j) => [a, ramp[j]]));

    const defs = DATA.segments.definition;
    document.getElementById("t-actions").innerHTML = `<table><thead><tr><th>Segment</th><th>Action</th><th>Owner</th><th>Timing</th><th>KPI</th></tr></thead><tbody>${
      defs.map((d) => `<tr><td><i class="swatch" style="background:${segColor(d.segment_name)}"></i>${d.segment_name}</td><td>${d.action}</td><td>${d.owner}</td><td>${d.timing}</td><td>${d.kpi}</td></tr>`).join("")}</tbody></table>`;
  }

  const THEMES = () => Object.entries(DATA.cube.themes);
  function renderCrossSell() {
    const rs = rows(), cust = total(rs, "customers");
    kpis("kpi-cs", [
      ["Customers with ≥1 signal", fmtInt.format(total(rs, "any_signal")), pct(total(rs, "any_signal") / cust) + " of selection"],
      ["Addressable balance", inr(total(rs, "addressable")), "latest balance of flagged customers"],
      ["Avg opportunity score", fmt1.format(total(rs, "score_sum") / cust), "0-100"],
      ["Tier A customers", fmtInt.format(by(rows("tier"), "tier", ["customers"])[0].customers * (state.tier === "All" || state.tier === "A" ? 1 : 0)), "top 5% by score"],
    ]);
    const th = THEMES();
    const counts = th.map(([k]) => total(rs, "sig_" + k));
    draw("c-themes", {
      type: "bar",
      data: { labels: th.map(([, n]) => n), datasets: [{ label: "Customers flagged", data: counts, ...bar(css("--s1")) }] },
      options: baseOptions({ indexAxis: "y", scales: { x: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") } }, y: { grid: { display: false }, ticks: { color: css("--ink-2") } } } }),
    }, { head: ["Theme", "Customers flagged", "% of selection"], rows: th.map(([, n], i) => [n, fmtInt.format(counts[i]), pct(counts[i] / cust)]) });

    // theme x segment heat table (share of segment flagged)
    const segs = by(rows("segment"), "segment", ["customers", ...th.map(([k]) => "sig_" + k)]);
    const cell = (v) => { const t = Math.min(1, v / 0.6); return `background:color-mix(in srgb, var(--seq-1) ${Math.round(t * 85)}%, transparent);${t > 0.6 ? "color:#fff" : ""}`; };
    document.getElementById("t-heat").innerHTML = `<table class="heat"><thead><tr><th>Segment</th>${th.map(([, n]) => `<th class="num">${n}</th>`).join("")}</tr></thead><tbody>${
      DIMS.segment.map((s, i) => `<tr><td style="text-align:left"><i class="swatch" style="background:${segColor(s)}"></i>${s}</td>${th.map(([k]) => { const v = segs[i]["sig_" + k] / (segs[i].customers || 1); return `<td style="${cell(v)}" title="${fmtInt.format(segs[i]["sig_" + k])} customers">${pct(v)}</td>`; }).join("")}</tr>`).join("")}</tbody></table>`;

    const tiers = by(rows("tier"), "tier", ["customers", "addressable"]);
    draw("c-tiers", {
      type: "bar",
      data: { labels: DIMS.tier.map((t) => t === "Watch" ? "Watch" : "Tier " + t), datasets: [{ label: "Customers", data: tiers.map((t) => t.customers), ...bar(DIMS.tier.map((t) => css(TIER_VARS[t]))) }] },
      options: baseOptions({ scales: { x: { grid: { display: false }, ticks: { color: css("--ink-2") } }, y: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") }, border: { display: false } } } }),
    }, { head: ["Tier", "Customers", "Addressable balance"], rows: DIMS.tier.map((t, i) => [t, fmtInt.format(tiers[i].customers), inr(tiers[i].addressable)]) });

    // score histogram (whole base)
    const bins = Array.from({ length: 40 }, (_, i) => i + 1);
    const ds = DIMS.tier.map((t) => ({ label: t === "Watch" ? "Watch" : "Tier " + t, data: bins.map((b) => (DATA.score_hist.find((h) => h.tier === t && h.bin === b) || { n: 0 }).n), backgroundColor: css(TIER_VARS[t]), borderSkipped: false, barPercentage: 1, categoryPercentage: 0.92 }));
    draw("c-score", {
      type: "bar",
      data: { labels: bins.map((b) => (b - 1) * 2.5), datasets: ds },
      options: baseOptions({ plugins: { legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip, callbacks: { title: (c) => `Score ${c[0].label}-${+c[0].label + 2.5}` } } }, scales: { x: { stacked: true, grid: { display: false }, ticks: { color: css("--ink-2"), maxTicksLimit: 11 } }, y: { stacked: true, ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") }, border: { display: false } } } }),
    }, { head: ["Score from", ...DIMS.tier], rows: bins.map((b, i) => [(b - 1) * 2.5, ...ds.map((d) => fmtInt.format(d.data[i]))]) });
    legend("c-score", DIMS.tier.map((t) => [t === "Watch" ? "Watch" : "Tier " + t, css(TIER_VARS[t])]));

    const oc = by(rows("city"), "city", ["any_signal"]).map((v, i) => ({ city: DIMS.city[i], n: v.any_signal })).filter((c) => !["Other cities", "Unknown"].includes(c.city)).sort((a, b) => b.n - a.n).slice(0, 12);
    draw("c-oppcity", {
      type: "bar",
      data: { labels: oc.map((c) => c.city), datasets: [{ label: "Customers with a signal", data: oc.map((c) => c.n), ...bar(css("--s1")) }] },
      options: baseOptions({ indexAxis: "y", scales: { x: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") } }, y: { grid: { display: false }, ticks: { color: css("--ink-2") } } } }),
    }, { head: ["City", "Customers with a signal"], rows: oc.map((c) => [c.city, fmtInt.format(c.n)]) });
  }

  let page = 0;
  const PAGE_SIZE = 25;
  function priorityRows() {
    const top = new Set(DIMS.city.slice(0, DIMS.city.length - 2));
    const theme = document.getElementById("f-theme").value;
    return DATA.priority.filter((p) =>
      (state.segment === "All" || p.segment === state.segment) && (state.age_group === "All" || p.age_group === state.age_group) &&
      (state.gender === "All" || p.gender === state.gender) && (state.tier === "All" || p.tier === state.tier) &&
      (state.evidence === "All" || p.evidence === state.evidence) && (theme === "All" || p.theme === theme) &&
      (state.city === "All" || (state.city === "Other cities" ? !top.has(p.city) && p.city !== "UNKNOWN" : state.city === "Unknown" ? p.city === "UNKNOWN" : p.city === state.city)));
  }
  function renderManager() {
    const rs = rows(), cust = total(rs, "customers");
    const tiers = by(rows("tier"), "tier", ["customers", "addressable"]);
    kpis("kpi-mgr", [
      ["How large: addressable balance", inr(total(rs, "addressable")), "latest balance of customers with a signal"],
      ["Tier A in selection", fmtInt.format(state.tier === "All" || state.tier === "A" ? tiers[0].customers : 0), "work these first"],
      ["Customers in selection", fmtInt.format(cust), ""],
    ]);
    const list = priorityRows(), pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    page = Math.min(page, pages - 1);
    const slice = list.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    document.getElementById("t-priority").innerHTML = `<table class="priority"><thead><tr><th class="num">Rank</th><th>Customer</th><th>Tier</th><th class="num">Score</th><th>Why</th><th>What</th><th>Where</th><th>Segment</th><th>Evidence</th></tr></thead><tbody>${
      slice.map((p) => `<tr><td class="num">${fmtInt.format(p.priority_rank)}</td><td><code>${p.masked_id}</code></td><td><span class="tierchip ${p.tier}">${p.tier}</span></td><td class="num">${fmt1.format(p.score)}</td><td class="reason">${p.reason.split(" -> ")[0]}</td><td>${p.theme}</td><td>${p.city}</td><td>${p.segment}</td><td>${p.evidence}</td></tr>`).join("") ||
      `<tr><td colspan="9">No customers in the top ${fmtInt.format(DATA.priority.length)} match these filters.</td></tr>`}</tbody></table>`;
    document.getElementById("pager-info").textContent = `${fmtInt.format(list.length)} of the top ${fmtInt.format(DATA.priority.length)} priority customers · page ${page + 1} of ${pages}`;

    draw("c-mgrtier", {
      type: "bar",
      data: { labels: DIMS.tier.map((t) => t === "Watch" ? "Watch" : "Tier " + t), datasets: [{ label: "Customers", data: tiers.map((t) => t.customers), ...bar(DIMS.tier.map((t) => css(TIER_VARS[t]))) }] },
      options: baseOptions({ scales: { x: { grid: { display: false }, ticks: { color: css("--ink-2") } }, y: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") }, border: { display: false } } } }),
    }, { head: ["Tier", "Customers"], rows: DIMS.tier.map((t, i) => [t, fmtInt.format(tiers[i].customers)]) });

    const ti = DIM_ORDER.indexOf("tier"), ci = DIM_ORDER.indexOf("city");
    const ac = DIMS.city.map(() => 0);
    for (const r of rows("city")) if (DIMS.tier[r[ti]] === "A") ac[r[ci]] += r[M.customers];
    const top = DIMS.city.map((c, i) => ({ c, n: ac[i] })).filter((x) => !["Other cities", "Unknown"].includes(x.c)).sort((a, b) => b.n - a.n).slice(0, 10);
    draw("c-mgrcity", {
      type: "bar",
      data: { labels: top.map((x) => x.c), datasets: [{ label: "Tier A customers", data: top.map((x) => x.n), ...bar(css("--tierA")) }] },
      options: baseOptions({ indexAxis: "y", scales: { x: { ticks: { callback: short, color: css("--ink-2") }, grid: { color: css("--grid") } }, y: { grid: { display: false }, ticks: { color: css("--ink-2") } } } }),
    }, { head: ["City", "Tier A customers"], rows: top.map((x) => [x.c, fmtInt.format(x.n)]) });
  }

  function renderQuality() {
    const wf = DATA.waterfall;
    document.getElementById("t-waterfall").innerHTML = `<table><thead><tr><th>Step</th><th class="num">Rows</th></tr></thead><tbody>${
      wf.map((w) => `<tr><td>${w.step}</td><td class="num">${fmtInt.format(w.rows)}</td></tr>`).join("")}</tbody></table>`;
    document.getElementById("t-dq").innerHTML = `<table><thead><tr><th>Check</th><th>Dimension</th><th>Rule</th><th class="num">Pass %</th><th class="num">Target</th><th>Status</th></tr></thead><tbody>${
      DATA.dq.map((d) => `<tr><td>${d.check_id}</td><td>${d.dimension}</td><td>${d.rule}${d.note ? `<br><span style="color:var(--muted);font-size:12px">${d.note}</span>` : ""}</td><td class="num">${d.pass_pct == null ? "–" : fmt1.format(d.pass_pct)}</td><td class="num">${d.threshold_pct == null ? "–" : fmt1.format(d.threshold_pct)}</td><td><span class="badge ${d.status.toLowerCase()}">${d.status}</span></td></tr>`).join("")}</tbody></table>`;
    const cubeAll = DATA.cube.rows;
    const site = { "Total Customers": cubeAll.reduce((s, r) => s + r[M.customers], 0), "Total Transactions": cubeAll.reduce((s, r) => s + r[M.txns], 0), "Total Txn Value": cubeAll.reduce((s, r) => s + r[M.value], 0), "Opportunity Count": cubeAll.reduce((s, r) => s + r[M.any_signal], 0) };
    document.getElementById("t-recon").innerHTML = `<table><thead><tr><th>KPI</th><th class="num">SQL</th><th class="num">This dashboard</th><th class="num">Variance</th></tr></thead><tbody>${
      DATA.kpi_reconciliation.filter((k) => k.kpi in site).map((k) => { const v = site[k.kpi] - k.sql_value; return `<tr><td>${k.kpi}</td><td class="num">${fmtInt.format(Math.round(k.sql_value))}</td><td class="num">${fmtInt.format(Math.round(site[k.kpi]))}</td><td class="num">${Math.abs(v) < 1 ? "0" : fmt1.format(v)}</td></tr>`; }).join("")}</tbody></table>`;
  }

  const RENDER = [renderExecutive, renderSegments, renderCrossSell, renderManager, renderQuality];
  let tab = 0;
  function render() {
    RENDER[tab]();
    const act = DIM_ORDER.filter((d) => state[d] !== "All").map((d) => `${FILTERS.find((f) => f[0] === d)[1]}: ${state[d]}`);
    document.getElementById("active-filters").textContent = act.length ? "Filtered by " + act.join(" · ") : "Showing all customers";
  }

  // ------------------------------------------------------------------ init
  function buildFilters() {
    const box = document.getElementById("filters");
    box.innerHTML = FILTERS.map(([d, label]) =>
      `<label>${label}<select data-dim="${d}"><option>All</option>${DIMS[d].map((v) => `<option>${v}</option>`).join("")}</select></label>`).join("") +
      `<button class="reset" type="button" id="reset">Reset filters</button>`;
    box.addEventListener("change", (e) => { const d = e.target.dataset.dim; if (d) { state[d] = e.target.value; page = 0; render(); } });
    document.getElementById("reset").addEventListener("click", () => {
      DIM_ORDER.forEach((d) => (state[d] = "All")); box.querySelectorAll("select").forEach((s) => (s.value = "All"));
      document.getElementById("f-theme").value = "All"; page = 0; render();
    });
    const themeSel = document.getElementById("f-theme");
    themeSel.innerHTML = "<option>All</option>" + [...new Set(DATA.priority.map((p) => p.theme))].sort().map((t) => `<option>${t}</option>`).join("");
    themeSel.addEventListener("change", () => { page = 0; render(); });
  }
  function initTabs() {
    const btns = [...document.querySelectorAll(".tabs button")];
    const panels = [...document.querySelectorAll(".panel")];
    const show = (i) => {
      tab = i;
      btns.forEach((b, j) => b.setAttribute("aria-selected", String(j === i)));
      panels.forEach((p, j) => (p.hidden = j !== i));
      try { history.replaceState(null, "", "#" + panels[i].id); } catch (e) { /* file:// */ }
      render();
    };
    btns.forEach((b, i) => b.addEventListener("click", () => show(i)));
    const start = panels.findIndex((p) => "#" + p.id === location.hash);
    show(start >= 0 ? start : 0);
  }
  function initToggles() {
    document.querySelectorAll(".view-toggle").forEach((b) => b.addEventListener("click", () => {
      const card = b.closest(".card"); card.classList.toggle("show-table");
      b.textContent = card.classList.contains("show-table") ? "Chart" : "Table";
    }));
  }

  fetch("data/dashboard.json").then((r) => r.json()).then((d) => {
    DATA = d; DIMS = d.cube.dims;
    DIMS.age_group = DIMS.age_group; // keep key names aligned with DIM_ORDER
    M = Object.fromEntries(d.cube.measures.map((m, i) => [m, i + DIM_ORDER.length]));
    state = Object.fromEntries(DIM_ORDER.map((k) => [k, "All"]));
    document.getElementById("asof").textContent = `As of ${d.meta.as_of} · window ${d.meta.window_start} to ${d.meta.window_end} · generated ${d.meta.generated}`;
    document.getElementById("loading").remove();
    document.getElementById("dash").hidden = false;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    buildFilters(); initToggles(); initTabs();
    document.getElementById("prev").addEventListener("click", () => { page = Math.max(0, page - 1); renderManager(); });
    document.getElementById("next").addEventListener("click", () => { page += 1; renderManager(); });
    window.addEventListener("themechange", render);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  }).catch((e) => { document.getElementById("loading").textContent = "Could not load dashboard data: " + e; });
})();
