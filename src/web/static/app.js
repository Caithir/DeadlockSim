// Deadlock Combat Simulator — browser UI.
// All numbers come from the server's API; this file only holds UI state and rendering.
"use strict";

// ── Small helpers ────────────────────────────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);
const fmt = (v, d = 1) => (v == null || !isFinite(v) ? "-" : Number(v).toFixed(d));
const int = (v) => Math.round(v || 0).toLocaleString("en-US");
const pct = (v, d = 0) => (v == null || !isFinite(v) ? "-" : (v * 100).toFixed(d) + "%");
const signed = (v, d = 1) => (v > 0 ? "+" : "") + fmt(v, d);
const secs = (v) => (v == null || !isFinite(v) ? "-" : v.toFixed(2) + "s");
const clone = (o) => JSON.parse(JSON.stringify(o));
const SVG_NS = "http://www.w3.org/2000/svg";
const FALLBACK_ICON = "/static/ui/all_stats.png";

/** Create an element: h("div.cls", {attrs}, ...children). */
function h(spec, attrs, ...children) {
  const [tag, ...classes] = spec.split(".");
  const el = document.createElement(tag || "div");
  if (classes.length) el.className = classes.join(" ");
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "html") el.innerHTML = v;
    else if (k === "tip") el._tip = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value" || k === "checked" || k === "disabled" || k === "selected") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}
function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const c of children.flat()) if (c != null) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
function img(src, fallback, attrs) {
  // Try the API image, then the bundled icon, then a generic placeholder.
  const queue = [src, fallback, FALLBACK_ICON].filter(Boolean);
  const el = h("img", { src: queue.shift(), alt: "", ...attrs });
  el.addEventListener("error", () => { if (queue.length) el.src = queue.shift(); });
  return el;
}
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  },
};

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try { res = await fetch(path, opts); } catch { throw new Error("Cannot reach the simulator server."); }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status}).`);
  return data;
}

function toast(message, kind = "") {
  const el = h("div.toast" + (kind ? "." + kind : ""), {}, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3200);
}
const fail = (e) => toast(e.message || String(e), "error");

function openDialog(title, body, actions) {
  const dlg = $("#dialog");
  dlg.replaceChildren(h("h3", {}, title), ...[body].flat(), h("div.actions", {}, ...(actions || [h("button", { onclick: () => dlg.close() }, "Close")])));
  if (!dlg.open) dlg.showModal();
  return dlg;
}

// ── Tooltip ──────────────────────────────────────────────────────
const tipEl = $("#tooltip");
function placeTip(x, y) {
  const r = tipEl.getBoundingClientRect();
  tipEl.style.left = Math.max(4, Math.min(x + 14, innerWidth - r.width - 8)) + "px";
  tipEl.style.top = Math.max(4, Math.min(y + 14, innerHeight - r.height - 8)) + "px";
}
function showTip(content, x, y) {
  if (typeof content === "string") tipEl.innerHTML = content; else tipEl.replaceChildren(content);
  tipEl.hidden = false;
  placeTip(x, y);
}
const hideTip = () => { tipEl.hidden = true; };
document.addEventListener("mouseover", (e) => {
  const el = e.target.closest ? e.target.closest("*") : null;
  let node = el;
  while (node && !node._tip) node = node.parentElement;
  if (!node) return hideTip();
  const content = typeof node._tip === "function" ? node._tip() : node._tip;
  if (content) showTip(content, e.clientX, e.clientY); else hideTip();
});
document.addEventListener("mousemove", (e) => { if (!tipEl.hidden && !tipEl.dataset.chart) placeTip(e.clientX, e.clientY); });
document.addEventListener("focusin", (e) => {
  if (e.target._tip && e.target.matches(":focus-visible")) {
    const r = e.target.getBoundingClientRect();
    showTip(typeof e.target._tip === "function" ? e.target._tip() : e.target._tip, r.right, r.top);
  }
});
document.addEventListener("focusout", hideTip);

// ── State ────────────────────────────────────────────────────────
const SAVED_KEY = "deadlocksim_saved_builds";
const STATE_KEY = "deadlocksim_state_v2";
const TABS = ["Build", "Analysis", "Simulation", "Compare", "Saved Builds", "Heroes", "Patch Notes", "Settings"];
const S = {
  catalog: null, heroes: {}, items: {},
  build: { hero: "", items: [], extra_souls: 0, ability_upgrades: {} },
  settings: {},
  defender: { hero: "", items: [], boons: 10 },
  ui: { tab: "Build", cat: "all", tier: "all", sort: "Cost", search: "", legendary: false, goal: "balanced" },
  view: null, scores: {}, simScores: null, undo: [], redo: [], seq: 0,
};

function persist() {
  store.set(STATE_KEY, { build: S.build, settings: S.settings, defender: S.defender, ui: S.ui });
}
const buildReq = (build = S.build) => ({ build, settings: S.settings });

/** Change the build through here so undo/redo and persistence stay consistent. */
function setBuild(next, { record = true } = {}) {
  if (record) { S.undo.push(clone(S.build)); if (S.undo.length > 100) S.undo.shift(); S.redo = []; }
  S.build = next;
  S.simScores = null;
  persist();
  refreshBuild();
}
function undo() { if (!S.undo.length) return; S.redo.push(clone(S.build)); setBuild(S.undo.pop(), { record: false }); }
function redo() { if (!S.redo.length) return; S.undo.push(clone(S.build)); setBuild(S.redo.pop(), { record: false }); }

async function addItem(name) {
  try {
    const r = await api("/api/build/add", { items: S.build.items, item: name });
    if (r.status === "added" || r.status === "upgraded") {
      setBuild({ ...clone(S.build), items: r.items });
      if (r.status === "upgraded") toast(r.message, "ok");
    } else toast(r.message);
  } catch (e) { fail(e); }
}
function removeItem(index) {
  const next = clone(S.build);
  next.items.splice(index, 1);
  setBuild(next);
}

// ── Charts ───────────────────────────────────────────────────────
const C = { bullet: "var(--s-bullet)", spirit: "var(--s-spirit)", melee: "var(--s-melee)", you: "var(--s-you)", them: "var(--s-them)" };
function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}
function legend(series) {
  return h("div.legend", {}, series.map((s) => h("span", {}, h("i", { style: `background:${s.color}` }), s.name)));
}
/** Shared frame: axes, gridlines, and a hover handler mapping x to an index. */
function frame({ width = 520, height = 220, yMax, xLabels, xTitle, yTitle, xTickEvery }) {
  const m = { l: 44, r: 12, t: 8, b: 30 };
  const W = width - m.l - m.r, H = height - m.t - m.b;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  const y = (v) => m.t + H - (v / yMax) * H;
  for (let i = 0; i <= 4; i++) {
    const v = (yMax * i) / 4;
    root.append(svg("line", { class: "grid", x1: m.l, x2: m.l + W, y1: y(v), y2: y(v) }));
    root.append(svg("text", { x: m.l - 6, y: y(v) + 3, "text-anchor": "end" }, v >= 1000 ? (v / 1000).toFixed(1) + "k" : +v.toFixed(1)));
  }
  root.append(svg("line", { class: "axis", x1: m.l, x2: m.l + W, y1: m.t + H, y2: m.t + H }));
  const n = xLabels.length;
  const every = xTickEvery || Math.max(1, Math.ceil(n / 10));
  const xAt = (i, band) => (band ? m.l + ((i + 0.5) / n) * W : m.l + (n > 1 ? (i / (n - 1)) * W : W / 2));
  if (xTitle) root.append(svg("text", { x: m.l + W / 2, y: height - 2, "text-anchor": "middle" }, xTitle));
  if (yTitle) root.append(svg("text", { x: 10, y: m.t + H / 2, "text-anchor": "middle", transform: `rotate(-90 10 ${m.t + H / 2})` }, yTitle));
  return { root, m, W, H, y, xAt, n, every };
}
function attachHover(wrap, f, band, tipFor, marker) {
  const hit = svg("rect", { x: f.m.l, y: f.m.t, width: f.W, height: f.H, fill: "transparent" });
  f.root.append(hit);
  hit.addEventListener("mousemove", (e) => {
    const r = hit.getBoundingClientRect();
    const frac = (e.clientX - r.left) / r.width;
    const i = Math.max(0, Math.min(f.n - 1, band ? Math.floor(frac * f.n) : Math.round(frac * (f.n - 1))));
    if (marker) marker(i);
    tipEl.dataset.chart = "1";
    showTip(tipFor(i), e.clientX, e.clientY);
  });
  hit.addEventListener("mouseleave", () => { delete tipEl.dataset.chart; hideTip(); if (marker) marker(-1); });
  wrap.append(f.root);
}
function tipTable(title, rows) {
  return h("div", {}, h("div", { style: "font-weight:700;margin-bottom:3px" }, title),
    rows.map(([color, name, value]) => h("div", { style: "display:flex;gap:10px;justify-content:space-between" },
      h("span", {}, color ? h("i", { style: `display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;background:${color}` }) : null, name), h("b", {}, value))));
}
/** Stacked bars: series = [{name, color, values}], one bar per x label. */
function stackedBars(xLabels, series, opts = {}) {
  const totals = xLabels.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  const f = frame({ ...opts, yMax: niceMax(Math.max(...totals, 0)), xLabels });
  const bw = Math.max(2, (f.W / f.n) * 0.72);
  xLabels.forEach((lbl, i) => {
    let acc = 0;
    for (const s of series) {
      const v = s.values[i];
      if (v <= 0) continue;
      const y1 = f.y(acc + v), y0 = f.y(acc);
      f.root.append(svg("rect", { x: f.xAt(i, true) - bw / 2, y: y1, width: bw, height: Math.max(0, y0 - y1 - 1), fill: s.color, rx: 1.5 }));
      acc += v;
    }
    if (i % f.every === 0) f.root.append(svg("text", { x: f.xAt(i, true), y: f.m.t + f.H + 12, "text-anchor": "middle" }, lbl));
  });
  const wrap = h("div.chart");
  if (series.length > 1) wrap.append(legend(opts.legend || series));
  attachHover(wrap, f, true, (i) => tipTable(`${opts.xPrefix || ""}${xLabels[i]}${opts.xSuffix || ""}`,
    [...series.filter((s) => s.values[i] > 0).map((s) => [s.color, s.name, fmt(s.values[i])]), ["", "Total", fmt(totals[i])]]));
  return wrap;
}
/** Lines: series = [{name, color, values}] over shared x labels; refs = [{value, label}]. */
function lineChart(xLabels, series, opts = {}) {
  const peak = Math.max(...series.flatMap((s) => s.values), ...(opts.refs || []).map((r) => r.value), 0);
  const f = frame({ ...opts, yMax: niceMax(peak), xLabels });
  for (const r of opts.refs || []) {
    f.root.append(svg("line", { x1: f.m.l, x2: f.m.l + f.W, y1: f.y(r.value), y2: f.y(r.value), stroke: "var(--muted)", "stroke-dasharray": "4 4" }));
    f.root.append(svg("text", { x: f.m.l + f.W, y: f.y(r.value) - 3, "text-anchor": "end" }, r.label));
  }
  xLabels.forEach((lbl, i) => { if (i % f.every === 0) f.root.append(svg("text", { x: f.xAt(i), y: f.m.t + f.H + 12, "text-anchor": "middle" }, lbl)); });
  for (const s of series) {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${f.xAt(i).toFixed(1)},${f.y(v).toFixed(1)}`).join("");
    f.root.append(svg("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round" }));
    if (opts.dots) s.values.forEach((v, i) => f.root.append(svg("circle", { cx: f.xAt(i), cy: f.y(v), r: 3.5, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 })));
  }
  const cross = svg("line", { y1: f.m.t, y2: f.m.t + f.H, stroke: "var(--muted)", visibility: "hidden" });
  f.root.append(cross);
  const wrap = h("div.chart");
  if (series.length > 1) wrap.append(legend(series));
  attachHover(wrap, f, false,
    (i) => tipTable(opts.tipTitle ? opts.tipTitle(i) : `${xLabels[i]}${opts.xSuffix || ""}`, series.map((s) => [s.color, s.name, fmt(s.values[i], opts.decimals ?? 1)])),
    (i) => { if (i < 0) cross.setAttribute("visibility", "hidden"); else { cross.setAttribute("visibility", "visible"); cross.setAttribute("x1", f.xAt(i)); cross.setAttribute("x2", f.xAt(i)); } });
  return wrap;
}

// ── Shared pieces ────────────────────────────────────────────────
function heroSelect(value, onchange, extra = []) {
  return h("select", { onchange: (e) => onchange(e.target.value) },
    [...extra, ...S.catalog.heroes.map((x) => x.name)].map((n) => h("option", { value: n, selected: n === value }, n)));
}
function numberField(label, value, onchange, attrs = {}) {
  return h("label.field", {}, label, h("input", { type: "number", value, ...attrs, onchange: (e) => onchange(Number(e.target.value) || 0) }));
}
function itemIcon(name, attrs = {}) {
  const it = S.items[name];
  return it ? img(it.image_url, it.fallback_image, { tip: () => it.tooltip_html, ...attrs }) : h("span", {}, name);
}
function miniItems(names) { return h("div.mini-items", {}, names.map((n) => itemIcon(n))); }
function table(headers, rows) {
  return h("table", {}, h("thead", {}, h("tr", {}, headers.map((x) => h("th" + (x.num ? ".num" : ""), {}, x.label ?? x)))),
    h("tbody", {}, rows.map((r) => (r.nodeType ? r : h("tr", {}, r.map((c, i) => h("td" + (headers[i].num ? ".num" : ""), {}, c)))))));
}
function busy(el, text = "Working…") { el.replaceChildren(h("p.muted", {}, text)); }

// ── Build tab ────────────────────────────────────────────────────
const SORTS = {
  "Cost": (i) => i.cost, "Name": (i) => i.name,
  "Weapon Damage %": (i) => -i.weapon_damage_pct, "Fire Rate %": (i) => -i.fire_rate_pct, "Bonus HP": (i) => -i.bonus_hp,
  "Bullet Resist %": (i) => -i.bullet_resist_pct, "Spirit Resist %": (i) => -i.spirit_resist_pct, "Spirit Power": (i) => -i.spirit_power,
  "Lifesteal %": (i) => -(i.bullet_lifesteal + i.spirit_lifesteal), "HP Regen": (i) => -i.hp_regen,
  "Shields": (i) => -(i.bullet_shield + i.spirit_shield), "Bullet Shred %": (i) => -i.bullet_resist_shred,
  "Spirit Shred %": (i) => -i.spirit_resist_shred, "Cooldown Reduction %": (i) => -i.cooldown_reduction, "Spirit Amp %": (i) => -i.spirit_amp_pct,
};
const IMPACT_SORTS = { "★ Gun DPS": "dps_delta", "★ Spirit DPS": "spirit_delta", "★ EHP": "ehp_delta", "★ DPS / 1k souls": "dps_per_soul", "★ EHP / 1k souls": "ehp_per_soul" };
const SIM_SORTS = {
  "⚔ Sim gun DPS": ["sim_dps_delta", "gun"], "⚔ Sim spirit DPS": ["sim_dps_delta", "spirit"], "⚔ Sim hybrid DPS": ["sim_dps_delta", "hybrid"],
  "⚔ Sim DPS / 1k souls": ["sim_dps_per_soul", "hybrid"],
};
const SCORE_LABELS = {
  dps_delta: "Gun DPS", spirit_delta: "Spirit DPS", ehp_delta: "EHP", dps_per_soul: "DPS / 1k souls", ehp_per_soul: "EHP / 1k souls",
  sim_dps_delta: "Sim DPS", sim_ehp_delta: "EHP", sim_dps_per_soul: "Sim DPS / 1k souls", sim_ehp_per_soul: "EHP / 1k souls",
};
const ROMAN = ["", "I", "II", "III", "IV", "V"];

function renderBuildTab(main) {
  main.replaceChildren(h("div.build-layout", {}, h("section", { id: "build-panel" }), h("section", { id: "shop-panel" })));
  renderBuildPanel();
  renderShopPanel();
}

function renderBuildPanel() {
  const panel = $("#build-panel");
  if (!panel) return;
  const v = S.view, hero = S.heroes[S.build.hero];
  const els = [h("h2", {}, "Hero & abilities"),
    h("div.row", {},
      h("label.field", {}, "Hero", heroSelect(S.build.hero, (name) => setBuild({ ...clone(S.build), hero: name }))),
      numberField("Extra souls", S.build.extra_souls, (n) => setBuild({ ...clone(S.build), extra_souls: Math.max(0, n) }), { min: 0, step: 100, title: "Souls gathered beyond what the items cost" }))];
  if (v && hero) {
    els.push(h("div.infobar", {},
      h("span.gold", {}, h("b", {}, `${int(v.souls.total)} souls`)), h("span", {}, `${v.boons} boons`),
      h("span", { class: v.ap.spent > v.ap.total ? "bad" : "" }, `AP ${v.ap.remaining}/${v.ap.total}`),
      v.souls.to_next_boon ? h("span.muted", {}, `next boon in ${int(v.souls.to_next_boon)}`) : null));
    els.push(h("div.hero-head", {}, img(hero.icon_url || hero.hero_card_url), h("div", {}, h("b.gold", {}, hero.name), " ", h("span.pill." + v.summary.build_type, {}, v.summary.build_type),
      h("div.muted.small", {}, hero.role || ""))));
    for (const ab of v.abilities) {
      const info = hero.abilities[ab.index] || {};
      els.push(h("div.ability", { tip: () => abilityTip(info, ab) },
        img(ab.image_url), h("span.name", {}, ab.name), ab.dps ? h("span.dps", {}, `${fmt(ab.dps)} dps`) : null,
        ab.tiers.map((t) => h("button.tier-btn" + (t.active ? ".active" : t.can_buy ? ".buyable" : ""), {
          disabled: !t.active && !t.can_buy,
          "aria-pressed": String(t.active),
          tip: () => h("div", {}, h("b", {}, `${ab.name} — T${t.tier} `), h("span.muted", {}, t.active ? "(owned — click to remove)" : `(${t.cost} AP${t.can_buy ? "" : ", locked"})`),
            h("div", { html: t.description }), Math.abs(t.spirit_dps_delta) >= 0.1 ? h("div.tone-spirit", {}, `${signed(t.spirit_dps_delta)} spirit DPS`) : null),
          onclick: () => {
            const next = clone(S.build);
            const tier = t.active ? t.tier - 1 : t.tier;
            if (tier <= 0) delete next.ability_upgrades[ab.index]; else next.ability_upgrades[ab.index] = tier;
            setBuild(next);
          },
        }, `T${t.tier}`))));
    }
  }
  els.push(h("h2", {}, "Items"));
  const max = S.catalog.max_items;
  const slots = [];
  S.build.items.forEach((name, i) => {
    const it = S.items[name];
    if (!it) return;
    slots.push(h("button.slot.filled.cat-" + it.category, { "aria-label": `Remove ${name}`, onclick: () => removeItem(i),
      tip: () => it.tooltip_html + '<div class="tt-note">Click to remove</div>' }, img(it.image_url, it.fallback_image), h("span.cost", {}, int(it.cost))));
  });
  for (let i = S.build.items.length; i < max; i++) slots.push(h("div.slot"));
  els.push(h("div.slots", {}, slots));
  els.push(h("div.row", { style: "margin-top:8px" },
    h("button.tiny", { onclick: undo, disabled: !S.undo.length, title: "Undo (Ctrl+Z)" }, "Undo"),
    h("button.tiny", { onclick: redo, disabled: !S.redo.length, title: "Redo (Ctrl+Shift+Z)" }, "Redo"),
    h("button.tiny", { onclick: () => S.build.items.length && setBuild({ ...clone(S.build), items: [], ability_upgrades: {} }) }, "Clear"),
    h("span.spacer"),
    h("button.tiny", { onclick: importDialog }, "Import"),
    h("button.tiny", { onclick: shareBuild, disabled: !v || !v.share_code }, "Share"),
    h("button.tiny.primary", { onclick: saveDialog }, "Save")));
  for (const w of (v && v.warnings) || []) els.push(h("p.bad.small", {}, w));
  els.push(h("h2", {}, "Calculated stats"));
  if (v) {
    els.push(h("div.tiles", {}, v.sheet.tiles.map((t) => h("div.tile.tone-" + t.tone, {}, h("div.label", {}, t.label), h("div.value", {}, t.value), h("div.perk", {}, t.per_k || " ")))));
    for (const col of v.sheet.columns) {
      els.push(h("div.col-title.tone-" + col.tone, {}, col.title));
      if (!col.rows.length) els.push(h("div.muted.small", { style: "padding:2px 6px" }, col.empty_note));
      els.push(...col.rows.map(statRow));
    }
    els.push(h("hr", { style: "border:0;border-top:1px solid var(--line);margin:8px 0" }), ...v.sheet.footer.map(statRow));
    els.push(h("p.muted.small", {}, "“/k” is the gain per 1,000 souls. Rows with › open a breakdown."));
  } else els.push(h("p.muted", {}, "Calculating…"));
  panel.replaceChildren(...els);
}
function abilityTip(info, ab) {
  const stats = [info.base_damage && `Damage ${fmt(info.base_damage, 0)}`, info.spirit_scaling && `Scale ${fmt(info.spirit_scaling, 2)}x`, info.cooldown > 0 && `CD ${fmt(info.cooldown)}s`, info.duration && `Duration ${fmt(info.duration)}s`].filter(Boolean);
  return h("div", {}, h("div.tt-name.tone-spirit", {}, ab.name), h("div.tt-foot-label", {}, (info.ability_type || "").replace(/_/g, " ")),
    h("div.tt-desc", { html: (info.description || "").replace(/<svg[\s\S]*?<\/svg>/g, "") }), h("div.tone-spirit", {}, stats.join(" · ")),
    ab.dps ? h("div", {}, `In this build: ${fmt(ab.damage)} damage, ${fmt(ab.dps)} DPS`) : null);
}
function statRow(r) {
  const cells = [h("span.label", {}, r.label), h("span.value", {}, r.value), h("span.bonus", {}, r.bonus), h("span.perk", {}, r.per_k)];
  if (!r.breakdown.length) return h("div.stat-row", {}, cells);
  return h("button.stat-row", { onclick: () => openDialog(r.label, [
    ...r.breakdown.map((b) => h("div.line", {}, h("span.muted", {}, b.source), h("span.num", {}, b.value))),
    r.total ? h("div.line", { style: "font-weight:700;border:0" }, h("span", {}, "Total"), h("span.num", {}, r.total)) : null]) }, cells);
}

function activeScore() {
  const sort = S.ui.sort;
  if (IMPACT_SORTS[sort]) return { key: IMPACT_SORTS[sort], scores: S.scores };
  if (SIM_SORTS[sort]) return { key: SIM_SORTS[sort][0], scores: (S.simScores && S.simScores.sort === sort && S.simScores.scores) || null, sim: true };
  return null;
}
function renderShopPanel() {
  const panel = $("#shop-panel");
  if (!panel) return;
  const cats = [["all", "All"], ["weapon", "Weapon"], ["vitality", "Vitality"], ["spirit", "Spirit"]];
  const set = (k, v) => { S.ui[k] = v; persist(); if (k === "sort" && SIM_SORTS[v]) loadSimScores(); renderShopPanel(); };
  const filters = h("div.filters", {},
    h("div.cat-tabs", {}, cats.map(([v, label]) => h("button", { "aria-pressed": String(S.ui.cat === v), onclick: () => set("cat", v) }, label))),
    h("label.field", {}, "Tier", h("select", { onchange: (e) => set("tier", e.target.value) },
      ["all", "1", "2", "3", "4", "5"].map((t) => h("option", { value: t, selected: S.ui.tier === t }, t === "all" ? "All tiers" : "Tier " + t)))),
    h("label.field", {}, "Sort by", h("select", { onchange: (e) => set("sort", e.target.value) },
      [...Object.keys(SORTS), ...Object.keys(IMPACT_SORTS), ...Object.keys(SIM_SORTS)].map((n) => h("option", { value: n, selected: S.ui.sort === n }, n)))),
    h("label.field", {}, "Search ( / )", h("input", { type: "search", id: "shop-search", value: S.ui.search, placeholder: "item name…",
      oninput: (e) => { S.ui.search = e.target.value; renderShopGrid(); } })),
    h("label.check", {}, h("input", { type: "checkbox", checked: S.ui.legendary, onchange: (e) => set("legendary", e.target.checked) }), "Legendary"));
  panel.replaceChildren(filters, h("div.shop", { id: "shop-grid" }));
  renderShopGrid();
}
function renderShopGrid() {
  const grid = $("#shop-grid");
  if (!grid) return;
  const owned = new Set(S.build.items);
  const q = S.ui.search.trim().toLowerCase();
  let list = S.catalog.items.filter((i) => !owned.has(i.name) && (S.ui.cat === "all" || i.category === S.ui.cat) &&
    (S.ui.tier === "all" ? S.ui.legendary || i.tier < 5 : String(i.tier) === S.ui.tier) && (!q || i.name.toLowerCase().includes(q)));
  const act = activeScore();
  const perSoul = act && act.key.includes("per_soul");
  const scoreOf = (i) => { const s = act && act.scores && act.scores[i.name]; return s ? s[act.key] * (perSoul ? 1000 : 1) : 0; };
  if (act) {
    if (!act.scores) return busy(grid, "Running simulations for every item…");
    list = list.filter((i) => Math.abs(scoreOf(i)) >= 0.01).sort((a, b) => scoreOf(b) - scoreOf(a));
  } else {
    const key = SORTS[S.ui.sort] || SORTS.Cost;
    list.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : a.cost - b.cost || a.name.localeCompare(b.name); });
  }
  const card = (it) => {
    const sc = act ? scoreOf(it) : null;
    const fast = S.scores[it.name];
    return h("button.item-card.cat-" + it.category, { onclick: () => addItem(it.name), "aria-label": `Add ${it.name}`, tip: () => it.tooltip_html + impactHtml(it, act) },
      h("span.tier", {}, ROMAN[it.tier] || ""), fast && fast.consumes.length ? h("span.up", { title: "Upgrades an item you own" }, "▲") : null,
      img(it.image_url, it.fallback_image),
      sc != null ? h("span.badge", { class: sc > 0 ? "badge good" : "badge bad" }, signed(sc) + (perSoul ? "/k" : "")) : null,
      h("span.nm", {}, it.name));
  };
  const out = [];
  if (!list.length) out.push(h("p.muted", {}, act ? "No unowned item changes this metric." : "No items match these filters."));
  if (!act && S.ui.sort === "Cost" && !q) {
    for (const tier of [1, 2, 3, 4, 5]) {
      const inTier = list.filter((i) => i.tier === tier);
      if (!inTier.length) continue;
      out.push(h("div.tier-head", {}, `TIER ${tier}`, h("span.gold", {}, `${int(Math.min(...inTier.map((i) => i.cost)))}+ souls`)));
      for (const cat of ["weapon", "vitality", "spirit"]) {
        const group = inTier.filter((i) => i.category === cat);
        if (group.length) out.push(h("div.cat-group.cat-" + cat, {}, h("div.cat-label", {}, cat), h("div.cards", {}, group.map(card))));
      }
    }
  } else out.push(h("div.cards", {}, list.map(card)));
  grid.replaceChildren(...out);
}
function impactHtml(it, act) {
  const fast = S.scores[it.name];
  const sim = act && act.sim && act.scores && act.scores[it.name];
  const src = sim || fast;
  if (!src) return "";
  let rows = "";
  for (const [k, label] of Object.entries(SCORE_LABELS)) {
    if (src[k] == null || Math.abs(src[k]) < 0.01 / (k.includes("per_soul") ? 1000 : 1)) continue;
    rows += `<div><span>${label}</span><b>${signed(src[k] * (k.includes("per_soul") ? 1000 : 1))}</b></div>`;
  }
  const pay = src.consumes && src.consumes.length ? `<div><span>Upgrade from ${src.consumes.join(" + ")}</span><b>${int(src.purchase_cost)} souls</b></div>` : "";
  return rows || pay ? `<div class="impact"><div class="tt-foot-label">Impact on this build</div>${rows}${pay}</div>` : "";
}

async function refreshBuild() {
  const seq = ++S.seq;
  renderBuildPanel();
  renderShopGrid();
  try {
    const view = await api("/api/build/evaluate", buildReq());
    if (seq !== S.seq) return;
    const first = !S.view;
    S.view = view;
    renderBuildPanel();
    // Analysis always reflects the current build; other tabs only need the first result.
    if (S.ui.tab === "Analysis" || (first && S.ui.tab !== "Build")) renderTab();
    const fast = await api("/api/build/scores", { ...buildReq(), mode: "fast" });
    if (seq !== S.seq) return;
    S.scores = fast.scores;
    renderShopGrid();
    if (SIM_SORTS[S.ui.sort]) loadSimScores();
  } catch (e) { fail(e); }
}
async function loadSimScores() {
  const sort = S.ui.sort, seq = S.seq;
  if (S.simScores && S.simScores.sort === sort) return;
  try {
    const r = await api("/api/build/scores", { ...buildReq(), mode: SIM_SORTS[sort][1] });
    if (seq !== S.seq || S.ui.sort !== sort) return;
    S.simScores = { sort, scores: r.scores };
    renderShopGrid();
  } catch (e) { fail(e); }
}

// ── Save / share / import ────────────────────────────────────────
const savedBuilds = () => store.get(SAVED_KEY, []).filter((b) => b && b.hero_name);
function savedToBuild(b) {
  const ups = (b.ability_upgrades && (b.ability_upgrades[b.hero_name] || b.ability_upgrades)) || {};
  const clean = {};
  for (const [k, v] of Object.entries(ups)) if (Number.isInteger(+k) && typeof v === "number") clean[k] = v;
  return { hero: b.hero_name, items: (b.items || []).filter((n) => S.items[n]), extra_souls: b.extra_souls || 0, ability_upgrades: clean };
}
function saveDialog() {
  if (!S.view || !S.build.items.length) return toast("Add items before saving a build.");
  const name = h("input", { type: "text", value: `${S.build.hero} ${S.view.summary.build_type}`, maxlength: 60 });
  const save = () => {
    const title = name.value.trim();
    if (!title) return toast("Enter a build name.");
    const sm = S.view.summary;
    const list = savedBuilds();
    list.push({ id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()), hero_name: S.build.hero, build_name: title, build_type: sm.build_type,
      items: S.build.items, extra_souls: S.build.extra_souls, ability_upgrades: { [S.build.hero]: S.build.ability_upgrades },
      gun_dps: +sm.gun_dps.toFixed(1), spirit_dps: +sm.spirit_dps.toFixed(1), ehp: Math.round(sm.effective_hp), total_cost: S.view.souls.items,
      share_code: S.view.share_code, saved_at: new Date().toISOString() });
    store.set(SAVED_KEY, list);
    $("#dialog").close();
    toast(`Saved “${title}”.`, "ok");
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  openDialog("Save build", h("label.field", {}, "Build name", name), [h("button", { onclick: () => $("#dialog").close() }, "Cancel"), h("button.primary", { onclick: save }, "Save")]);
  name.select();
}
function shareUrl(code) { return `${location.origin}${location.pathname}#b=${code}`; }
async function shareBuild() {
  const url = shareUrl(S.view.share_code);
  try { await navigator.clipboard.writeText(url); toast("Share link copied to clipboard.", "ok"); }
  catch { openDialog("Share build", [h("p.muted.small", {}, "Copy this link:"), h("input", { type: "text", value: url, readonly: true, onfocus: (e) => e.target.select() })]); }
  history.replaceState(null, "", "#b=" + S.view.share_code);
}
async function loadCode(code, quiet) {
  const m = String(code).trim().match(/v1-[0-9a-z.\-]+/i);
  if (!m) return toast("That does not look like a build code or link.", "error");
  try {
    const r = await api("/api/share/decode?code=" + encodeURIComponent(m[0]));
    setBuild({ hero: r.build.hero, items: r.build.items, extra_souls: r.build.extra_souls, ability_upgrades: r.build.ability_upgrades });
    r.warnings.forEach((w) => toast(w));
    if (!quiet) toast(`Loaded ${r.build.hero} build.`, "ok");
    switchTab("Build");
  } catch (e) { fail(e); }
}
function importDialog() {
  const box = h("input", { type: "text", placeholder: "v1-… or a share link" });
  const go = () => { $("#dialog").close(); loadCode(box.value); };
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  openDialog("Import build", h("label.field", {}, "Build code or link", box), [h("button", { onclick: () => $("#dialog").close() }, "Cancel"), h("button.primary", { onclick: go }, "Load")]);
}

// ── Analysis tab ─────────────────────────────────────────────────
function goalSelect(onchange) {
  const names = { gun: "Gun DPS", spirit: "Spirit DPS", damage: "Total damage", tank: "Survivability", balanced: "Balanced" };
  return h("label.field", {}, "Goal", h("select", { onchange: (e) => { S.ui.goal = e.target.value; persist(); onchange(); } },
    S.catalog.goals.map((g) => h("option", { value: g, selected: S.ui.goal === g }, names[g] || g))));
}
function renderAnalysisTab(main) {
  const recs = h("div"), opt = h("div"), curve = h("div"), match = h("div");
  const budget = h("input", { type: "number", value: Math.max(15000, S.view ? S.view.souls.total : 0), min: 0, step: 500 });
  const maxTier = h("select", {}, [4, 5, 3, 2].map((t) => h("option", { value: t }, t === 5 ? "Up to legendary" : `Up to tier ${t}`)));
  const loadRecs = async () => {
    busy(recs);
    try {
      const r = await api("/api/build/recommend", { ...buildReq(), goal: S.ui.goal, limit: 10 });
      recs.replaceChildren(r.recommendations.length ? table(["Item", { label: "Pay", num: true }, { label: "Gun DPS", num: true }, { label: "Spirit DPS", num: true }, { label: "EHP", num: true }, ""],
        r.recommendations.map((x) => [h("span.row", {}, itemIcon(x.item, { style: "width:22px;height:22px" }), x.item, x.consumes.length ? h("span.muted.small", {}, `(upgrades ${x.consumes.join(", ")})`) : null),
          int(x.purchase_cost), signed(x.gun_dps_delta), signed(x.spirit_dps_delta), signed(x.ehp_delta, 0), h("button.tiny", { onclick: () => addItem(x.item) }, "Add")]))
        : h("p.muted", {}, "No purchase improves this goal."));
    } catch (e) { recs.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const runOpt = async () => {
    busy(opt, "Searching builds…");
    try {
      const r = await api("/api/build/optimize", { ...buildReq(), goal: S.ui.goal, budget: Number(budget.value) || 0, max_tier: Number(maxTier.value) });
      const res = r.result;
      opt.replaceChildren(
        h("p", {}, h("span.pill." + r.build_type, {}, r.build_type), ` ${res.items.length} items · ${int(res.total_cost)} of ${int(res.budget)} souls`,
          res.locked.length ? h("span.muted", {}, ` · kept ${res.locked.length} current item${res.locked.length > 1 ? "s" : ""}`) : null),
        h("div.muted.small", {}, "Suggested purchase order"), miniItems(r.purchase_order),
        table(["", { label: "Before", num: true }, { label: "After", num: true }, { label: "Change", num: true }],
          [["Gun DPS", "gun_dps"], ["Spirit DPS", "spirit_dps"], ["Effective HP", "effective_hp"]].map(([l, k]) => [l, fmt(res.before[k]), fmt(res.after[k]), signed(res.after[k] - res.before[k])])),
        h("div.row", { style: "margin-top:8px" }, h("button.primary", { onclick: () => { setBuild({ ...clone(S.build), items: r.purchase_order }); toast("Optimized build loaded.", "ok"); switchTab("Build"); } }, "Use this build")));
    } catch (e) { opt.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const loadCurves = async () => {
    busy(curve);
    try {
      const r = await api("/api/build/curves", buildReq());
      const p = r.power;
      const els = [];
      if (p.length > 1) {
        const labels = p.map((x) => (x.souls / 1000).toFixed(1) + "k");
        const tip = (i) => (i ? `${p[i].item} — ${int(p[i].souls)} souls, ${p[i].boons} boons` : "No items");
        els.push(h("div.chart-title", {}, "DPS after each purchase"),
          lineChart(labels, [{ name: "Gun DPS", color: C.bullet, values: p.map((x) => x.gun_dps) }, { name: "Spirit DPS", color: C.spirit, values: p.map((x) => x.spirit_dps) }], { dots: true, xTitle: "Souls spent", tipTitle: tip, height: 190 }),
          h("div.chart-title", {}, "Effective HP after each purchase"),
          lineChart(labels, [{ name: "Effective HP", color: C.melee, values: p.map((x) => x.effective_hp) }], { dots: true, xTitle: "Souls spent", tipTitle: tip, decimals: 0, height: 170 }));
        const differs = r.suggested_order.join("|") !== r.order.join("|");
        els.push(h("div.row", {}, h("span.muted.small", {}, differs ? "A more efficient purchase order exists:" : "Items are already in an efficient purchase order."),
          differs ? h("button.tiny", { onclick: () => setBuild({ ...clone(S.build), items: r.suggested_order }) }, "Reorder items") : null));
        if (differs) els.push(miniItems(r.suggested_order));
      } else els.push(h("p.muted", {}, "Add items to see how the build grows with each purchase."));
      if (r.range.some((x) => x.dps > 0)) {
        els.push(h("div.chart-title", {}, `Gun DPS by range (falloff ${fmt(r.falloff.start, 0)}–${fmt(r.falloff.end, 0)} m)`),
          lineChart(r.range.map((x) => x.distance), [{ name: "Sustained gun DPS", color: C.bullet, values: r.range.map((x) => x.dps) }],
            { xTitle: "Distance (m)", xSuffix: " m", height: 170, xTickEvery: Math.ceil(r.range.length / 8) }));
      }
      curve.replaceChildren(...els);
    } catch (e) { curve.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const loadMatch = async () => {
    busy(match);
    try {
      const r = await api("/api/build/matchups", buildReq());
      match.replaceChildren(h("p", {}, `Wins `, h("b", { class: r.wins * 2 >= r.total ? "good" : "bad" }, `${r.wins} of ${r.total}`), ` gun duels at ${r.boons} boons `,
        h("span.muted.small", {}, `(${pct(r.accuracy)} accuracy, ${pct(r.headshot_rate)} headshots; opponents have no items)`)),
        table(["Opponent", { label: "HP", num: true }, { label: "You kill in", num: true }, { label: "They kill in", num: true }, { label: "Margin", num: true }],
          r.matchups.map((m) => [m.opponent + (m.one_mag ? " ●" : ""), int(m.opponent_hp), secs(m.time_to_kill), secs(m.time_to_die),
            h("span", { class: m.margin > 0 ? "good" : m.margin < 0 ? "bad" : "" }, m.margin == null ? "-" : signed(m.margin, 2) + "s")])),
        h("p.muted.small", {}, "● = killed without reloading. Margin is how much sooner you finish the duel."));
    } catch (e) { match.replaceChildren(h("p.bad", {}, e.message)); }
  };
  main.replaceChildren(buildSummaryBar(), h("div.grid2", {},
    h("div.card", {}, h("h2", {}, "Next best purchases"), h("div.row", {}, goalSelect(loadRecs)), recs),
    h("div.card", {}, h("h2", {}, "Build optimizer"),
      h("div.row", { style: "align-items:flex-end" }, h("label.field", {}, "Soul budget", budget), h("label.field", {}, "Items", maxTier), h("button.primary", { onclick: runOpt }, "Optimize")),
      h("p.muted.small", {}, "Keeps the items already in your build and fills the rest for the selected goal."), opt),
    h("div.card", {}, h("h2", {}, "Power curve"), curve),
    h("div.card", {}, h("h2", {}, "Gun duel matchups"), match)));
  loadRecs(); loadCurves(); loadMatch();
}
function buildSummaryBar() {
  const v = S.view;
  if (!v) return h("p.muted", {}, "Calculating…");
  return h("div.banner", {}, h("div.row", {}, h("b.gold", {}, S.build.hero), h("span.pill." + v.summary.build_type, {}, v.summary.build_type),
    h("span.muted", {}, `${S.build.items.length} items · ${int(v.souls.total)} souls · ${v.boons} boons · gun ${fmt(v.summary.gun_dps)} · spirit ${fmt(v.summary.spirit_dps)} · EHP ${int(v.summary.effective_hp)}`),
    h("span.spacer"), h("button.tiny", { onclick: () => switchTab("Build") }, "Edit build")), S.build.items.length ? miniItems(S.build.items) : null);
}

// ── Simulation tab ───────────────────────────────────────────────
function renderSimulationTab(main) {
  const out = h("div"), mc = h("div");
  const def = S.defender;
  if (!S.heroes[def.hero]) def.hero = (S.catalog.heroes.find((x) => x.name !== S.build.hero) || S.catalog.heroes[0]).name;
  const defItems = h("div");
  const drawDef = () => defItems.replaceChildren(def.items.length ? h("div.mini-items", {}, def.items.map((n, i) => {
    const el = itemIcon(n, { style: "cursor:pointer" });
    el.addEventListener("click", () => { def.items.splice(i, 1); persist(); drawDef(); });
    return el;
  })) : h("p.muted.small", {}, "No defender items."), def.items.length ? h("p.muted.small", {}, "Click an item to remove it.") : null);
  const pick = h("input", { type: "text", list: "item-names", placeholder: "Add defender item…" });
  const addDef = async () => {
    if (!pick.value.trim()) return;
    try {
      const r = await api("/api/build/add", { items: def.items, item: pick.value.trim() });
      if (r.status === "added" || r.status === "upgraded") { def.items = r.items; pick.value = ""; persist(); drawDef(); } else toast(r.message);
    } catch (e) { fail(e); }
  };
  pick.addEventListener("keydown", (e) => { if (e.key === "Enter") addDef(); });
  const req = () => ({ ...buildReq(), defender: def });
  const run = async () => {
    busy(out, "Simulating…");
    try { renderSimResult(out, await api("/api/simulate", req())); } catch (e) { out.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const runMc = async () => {
    busy(mc, "Rolling duels…");
    try { renderMonteCarlo(mc, await api("/api/montecarlo", { ...req(), trials: 3000 })); } catch (e) { mc.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const st = S.settings;
  main.replaceChildren(buildSummaryBar(),
    h("datalist", { id: "item-names" }, S.catalog.items.map((i) => h("option", { value: i.name }))),
    h("div.grid2", {},
      h("div.card", {}, h("h2", {}, "Defender"),
        h("div.row", { style: "align-items:flex-end" }, h("label.field", {}, "Hero", heroSelect(def.hero, (n) => { def.hero = n; persist(); })),
          numberField("Boons", def.boons, (n) => { def.boons = Math.max(0, n); persist(); }, { min: 0, max: 50 }), pick, h("button", { onclick: addDef }, "Add")),
        defItems,
        h("p.muted.small", {}, `${fmt(st.duration, 0)}s fight · ${pct(st.accuracy)} accuracy · ${pct(st.headshot_rate)} headshots · ${fmt(st.distance, 0)} m · `,
          st.bidirectional ? "defender fights back" : "defender is passive", " — ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); switchTab("Settings"); } }, "change in Settings")),
        h("div.row", {}, h("button.primary", { onclick: run }, "Run simulation"), h("button", { onclick: runMc }, "Monte Carlo gun duel"))),
      h("div.card", {}, h("h2", {}, "Monte Carlo time-to-kill"), mc)),
    h("div.card", { style: "margin-top:14px" }, h("h2", {}, "Simulation results"), out));
  drawDef();
  mc.replaceChildren(h("p.muted", {}, "Rolls every shot for hit and headshot across thousands of gun duels to show how much the kill time can swing."));
  out.replaceChildren(h("p.muted", {}, "Run the simulation to see damage by source, DPS over time and the kill time."));
}
function renderSimResult(out, r) {
  const A = r.attacker.name, D = r.defender.name;
  let banner;
  if (r.bidirectional) {
    banner = r.winner === "a" ? h("div.banner.win", {}, h("strong.good", {}, `${A} wins at ${secs(r.kill_time)}`)) :
      r.winner === "b" ? h("div.banner.lose", {}, h("strong.bad", {}, `${D} wins at ${secs(r.defender_kill_time)}`)) :
      h("div.banner", {}, h("strong.gold", {}, `Draw — nobody died in ${fmt(r.duration)}s`));
    banner.append(h("div.muted.small", {}, `${A}: ${int(r.attacker_hp_remaining)} HP left · ${D}: ${int(r.target_hp_remaining)} HP left`));
  } else {
    banner = r.kill_time != null ? h("div.banner.win", {}, h("strong.good", {}, `${D} killed at ${secs(r.kill_time)}`)) :
      h("div.banner", {}, h("strong", {}, `${D} survived ${fmt(r.configured_duration, 0)}s with ${int(r.target_hp_remaining)} HP left`));
  }
  const side = (s) => h("div.card", {}, h("h3", {}, s.name),
    h("div.tiles", { style: "grid-template-columns:repeat(3,1fr)" },
      h("div.tile", {}, h("div.label", {}, "DPS"), h("div.value", {}, fmt(s.dps))),
      h("div.tile", {}, h("div.label", {}, "Total damage"), h("div.value", {}, int(s.total_damage))),
      h("div.tile", {}, h("div.label", {}, "Kill time"), h("div.value", {}, secs(s.kill_time)))),
    legend(["bullet", "spirit", "melee"].filter((t) => s.by_type[t] > 0).map((t) => ({ name: `${t[0].toUpperCase()}${t.slice(1)} ${pct(s.by_type[t] / (s.total_damage || 1))}`, color: C[t] }))),
    table(["Source", { label: "Damage", num: true }, { label: "DPS", num: true }, { label: "Share", num: true }],
      s.sources.map((x) => [x.source.replace(/_/g, " "), int(x.damage), fmt(x.dps), pct(x.share, 1)])),
    h("p.muted.small", {}, `${s.bullets_fired} shots · ${s.reloads} reloads` + Object.entries(s.procs).map(([k, n]) => ` · ${k} ×${n}`).join("")));
  const times = r.chart.times.map((t) => t.toFixed(1));
  const charts = [];
  for (const [cid, name] of r.bidirectional ? [["a", A], ["b", D]] : [["a", A]]) {
    const byType = { bullet: null, spirit: null, melee: null };
    for (const s of r.chart.series.filter((x) => x.combatant === cid)) {
      byType[s.damage_type] = byType[s.damage_type] ? byType[s.damage_type].map((v, i) => v + s.dps[i]) : s.dps.slice();
    }
    const series = Object.entries(byType).filter(([, v]) => v).map(([t, v]) => ({ name: t[0].toUpperCase() + t.slice(1), color: C[t], values: v }));
    if (series.length) charts.push(h("div", {}, h("div.chart-title", {}, `${name} — DPS over time by damage type`), stackedBars(times, series, { xTitle: "Time (s)", xSuffix: "s", height: 190 })));
  }
  const cum = [{ name: `${A} damage dealt`, color: C.you, values: r.chart.cumulative.a }];
  const refs = [{ value: r.defender.pool, label: `${D} HP ${int(r.defender.pool)}` }];
  if (r.chart.cumulative.b) { cum.push({ name: `${D} damage dealt`, color: C.them, values: r.chart.cumulative.b }); refs.push({ value: r.attacker.pool, label: `${A} HP ${int(r.attacker.pool)}` }); }
  charts.push(h("div", {}, h("div.chart-title", {}, "Cumulative damage vs. health pools"), lineChart(times, cum, { xTitle: "Time (s)", xSuffix: "s", refs, decimals: 0, height: 190 })));
  out.replaceChildren(banner, h("div.grid2", {}, r.sides.map(side)), h("div.grid2", { style: "margin-top:12px" }, charts));
}
function renderMonteCarlo(el, r) {
  const d = r.distribution;
  if (!d.kills) return el.replaceChildren(h("p", {}, `${r.attacker} never killed ${r.defender} within 3 minutes in ${int(d.trials)} duels.`));
  const labels = d.histogram.map((b) => b[0].toFixed(1));
  el.replaceChildren(
    h("div.tiles", {}, [["Median", secs(d.median)], ["10th–90th pct", `${fmt(d.p10)}–${fmt(d.p90)}s`], ["One magazine", pct(d.one_mag_rate)], ["Kill rate", pct(d.kill_rate)]]
      .map(([l, v]) => h("div.tile", {}, h("div.label", {}, l), h("div.value", {}, v)))),
    h("div.chart-title", {}, `Kill time across ${int(d.trials)} duels vs ${r.defender} (${int(d.target_hp)} HP)`),
    stackedBars(labels, [{ name: "Duels", color: C.you, values: d.histogram.map((b) => b[1]) }], { xTitle: "Time to kill (s)", xSuffix: "s", height: 180 }),
    h("p.muted.small", {}, `Fastest ${secs(d.min)}, slowest ${secs(d.max)}. The expected-value model gives ${secs(d.expected)}.`));
}

// ── Compare tab ──────────────────────────────────────────────────
function renderCompareTab(main) {
  const saved = savedBuilds();
  const options = [{ label: "Current build", build: S.build }, ...saved.map((b) => ({ label: `${b.build_name} (${b.hero_name})`, build: savedToBuild(b) }))];
  const sel = (idx) => h("select", {}, options.map((o, i) => h("option", { value: i, selected: i === idx }, o.label)));
  const a = sel(0), b = sel(Math.min(1, options.length - 1));
  const out = h("div");
  const run = async () => {
    busy(out);
    try {
      const r = await api("/api/build/compare", { a: options[a.value].build, b: options[b.value].build, settings: S.settings });
      const f = (row, v) => (row.fmt === "pct" ? pct(v) : row.fmt === "int" ? int(v) : fmt(v));
      out.replaceChildren(h("div.grid2", {},
        h("div", {}, h("h3", {}, "A — ", r.a.hero, " ", h("span.pill." + r.a.build_type, {}, r.a.build_type)), miniItems(r.a.items)),
        h("div", {}, h("h3", {}, "B — ", r.b.hero, " ", h("span.pill." + r.b.build_type, {}, r.b.build_type)), miniItems(r.b.items))),
        table(["Stat", { label: "A", num: true }, { label: "B", num: true }, { label: "B − A", num: true }], r.rows.map((row) => {
          const better = row.delta === 0 ? "" : (row.delta > 0) === row.higher_is_better ? "good" : "bad";
          return [row.label, f(row, row.a), f(row, row.b), h("span", { class: better }, (row.delta > 0 ? "+" : "") + f(row, row.delta))];
        })),
        r.only_a.length || r.only_b.length ? h("p.muted.small", {}, `Only in A: ${r.only_a.join(", ") || "—"} · Only in B: ${r.only_b.join(", ") || "—"}`) : null);
    } catch (e) { out.replaceChildren(h("p.bad", {}, e.message)); }
  };
  a.addEventListener("change", run); b.addEventListener("change", run);
  main.replaceChildren(h("div.card", {}, h("h2", {}, "Compare builds"),
    h("div.row", {}, h("label.field", {}, "Build A", a), h("label.field", {}, "Build B", b)),
    options.length < 2 ? h("p.muted", {}, "Save a build to compare it against the current one.") : out));
  if (options.length >= 2) run();
}

// ── Saved builds tab ─────────────────────────────────────────────
function renderSavedTab(main) {
  let filter = "All heroes";
  const grid = h("div.saved-grid");
  const draw = () => {
    const list = savedBuilds().filter((b) => filter === "All heroes" || b.hero_name === filter).sort((x, y) => (y.saved_at || "").localeCompare(x.saved_at || ""));
    if (!list.length) return grid.replaceChildren(h("p.muted", {}, "No saved builds yet. Use Save on the Build tab."));
    grid.replaceChildren(...list.map((b) => {
      const hero = S.heroes[b.hero_name];
      const when = b.saved_at ? new Date(b.saved_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
      return h("div.card.saved", {},
        h("div.row", {}, h("span.title", {}, b.build_name || "Unnamed build"), h("span.pill." + (b.build_type || "Hybrid"), {}, b.build_type || "Hybrid")),
        h("div.row.small", {}, hero ? img(hero.icon_url, null, { style: "width:22px;height:22px;border-radius:50%" }) : null, h("b.gold", {}, b.hero_name), h("span.muted", {}, `${int(b.total_cost)} souls`)),
        h("div.tiles", { style: "grid-template-columns:repeat(3,1fr);margin:8px 0 0" },
          [["Gun DPS", fmt(b.gun_dps), "weapon"], ["Spirit DPS", fmt(b.spirit_dps), "spirit"], ["EHP", int(b.ehp), "ehp"]].map(([l, v, t]) => h("div.tile.tone-" + t, {}, h("div.label", {}, l), h("div.value", {}, v)))),
        miniItems((b.items || []).filter((n) => S.items[n])),
        h("div.row", {}, h("span.muted.small", {}, when), h("span.spacer"),
          h("button.tiny", { onclick: () => { setBuild(savedToBuild(b)); toast(`Loaded “${b.build_name}”.`, "ok"); switchTab("Build"); } }, "Load"),
          b.share_code ? h("button.tiny", { onclick: () => navigator.clipboard.writeText(shareUrl(b.share_code)).then(() => toast("Share link copied.", "ok"), () => toast(shareUrl(b.share_code))) }, "Share") : null,
          h("button.tiny.danger", { onclick: () => openDialog("Delete build", h("p", {}, `Delete “${b.build_name}”? This cannot be undone.`), [
            h("button", { onclick: () => $("#dialog").close() }, "Cancel"),
            h("button.danger", { onclick: () => { store.set(SAVED_KEY, savedBuilds().filter((x) => x.id !== b.id)); $("#dialog").close(); draw(); } }, "Delete")]) }, "Delete")));
    }));
  };
  const exportAll = () => {
    const blob = new Blob([JSON.stringify(savedBuilds(), null, 2)], { type: "application/json" });
    const a = h("a", { href: URL.createObjectURL(blob), download: "deadlock-builds.json" });
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const file = h("input", { type: "file", accept: "application/json", hidden: true, onchange: async (e) => {
    try {
      const incoming = JSON.parse(await e.target.files[0].text());
      if (!Array.isArray(incoming)) throw new Error("File does not contain a list of builds.");
      const list = savedBuilds();
      const ids = new Set(list.map((b) => b.id));
      const fresh = incoming.filter((b) => b && b.hero_name && Array.isArray(b.items) && !ids.has(b.id));
      store.set(SAVED_KEY, [...list, ...fresh]);
      toast(`Imported ${fresh.length} build${fresh.length === 1 ? "" : "s"}.`, "ok");
      draw();
    } catch (err) { toast("Could not import: " + err.message, "error"); }
    e.target.value = "";
  } });
  main.replaceChildren(h("div.row", { style: "margin-bottom:10px;align-items:flex-end" },
    h("label.field", {}, "Hero", heroSelect(filter, (v) => { filter = v; draw(); }, ["All heroes"])), h("span.spacer"),
    h("button", { onclick: exportAll }, "Export all"), h("button", { onclick: () => file.click() }, "Import file"), file), grid,
    h("p.muted.small", {}, "Builds are stored in this browser. Export them to back up or move to another device."));
  draw();
}

// ── Heroes tab ───────────────────────────────────────────────────
function renderHeroesTab(main) {
  let name = S.build.hero, stat = "dps", boons = 0, other = S.defender.hero || S.catalog.heroes[0].name;
  const detail = h("div"), ranks = h("div"), versus = h("div");
  const kv = (rows) => table(["Stat", { label: "Value", num: true }], rows.filter(Boolean));
  const drawHero = () => {
    const x = S.heroes[name];
    const gun = x.base_bullet_damage > 0 || x.base_fire_rate > 0;
    detail.replaceChildren(h("div.hero-head", {}, img(x.icon_url || x.hero_card_url), h("div", {}, h("b.gold", {}, x.name), x.hero_labs ? h("span.bad.small", {}, " Hero Labs — stats may be incomplete") : null,
      h("div.muted.small", {}, [x.role, x.playstyle].filter(Boolean).join(" — ")))),
      h("div.grid2", {},
        h("div", {}, h("h3.tone-weapon", {}, "Weapon"), gun ? kv([["Bullet damage", `${fmt(x.base_bullet_damage, 2)}${x.pellets > 1 ? " × " + x.pellets : ""}`], ["Fire rate", fmt(x.base_fire_rate, 2) + " /s"],
          ["Base DPS", fmt(x.base_dps)], ["Magazine", x.base_ammo], ["Reload", fmt(x.reload_duration, 2) + "s"], ["Falloff", `${fmt(x.falloff_range_min, 0)}–${fmt(x.falloff_range_max, 0)} m`],
          ["Headshot multiplier", fmt(x.crit_bonus_start, 2) + "×"], ["Light / heavy melee", `${fmt(x.light_melee_damage, 0)} / ${fmt(x.heavy_melee_damage, 0)}`]]) : h("p.muted", {}, "No gun data.")),
        h("div", {}, h("h3.tone-vitality", {}, "Vitality & scaling"), kv([["HP", int(x.base_hp)], ["Regen", fmt(x.base_regen) + " /s"], ["Move / sprint speed", `${fmt(x.base_move_speed, 2)} / +${fmt(x.base_sprint)}`], ["Stamina", x.base_stamina],
          ["Bullet damage per boon", "+" + fmt(x.damage_gain, 2)], ["HP per boon", "+" + fmt(x.hp_gain, 0)], ["Spirit per boon", "+" + fmt(x.spirit_gain)]]))),
      h("h3.tone-spirit", {}, "Abilities"),
      ...x.abilities.filter((a) => a.name).map((a) => h("div.ability", { style: "align-items:flex-start" }, img(a.image_url, null, { style: "width:36px;height:36px" }),
        h("div", { style: "flex:1;min-width:0" }, h("b", {}, a.name), " ", h("span.muted.small", {}, (a.ability_type || "").replace(/_/g, " ")),
          h("div.small.tone-spirit", {}, [a.base_damage && `Dmg ${fmt(a.base_damage, 0)}`, a.spirit_scaling && `Spirit ×${fmt(a.spirit_scaling, 2)}`, a.cooldown > 0 && `CD ${fmt(a.cooldown)}s`, a.duration && `Dur ${fmt(a.duration)}s`].filter(Boolean).join(" · ")),
          a.upgrades.map((u) => h("div.small.muted", {}, h("b", {}, `T${u.tier} `), h("span", { html: u.description })))))));
    drawVersus();
  };
  const drawRanks = async () => {
    try {
      const r = await api(`/api/heroes/rankings?stat=${stat}&boons=${boons}`);
      const growth = stat.includes("growth");
      ranks.replaceChildren(table([{ label: "#", num: true }, "Hero", { label: stat.replace(/_/g, " "), num: true }],
        r.rankings.map((e) => h("tr.clickable", { onclick: () => { name = e.hero_name; picker.value = name; drawHero(); } },
          h("td.num", {}, e.rank), h("td", {}, e.hero_name), h("td.num", {}, growth ? pct(e.value, 1) : fmt(e.value, 2))))));
    } catch (e) { ranks.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const drawVersus = async () => {
    try {
      const r = await api(`/api/heroes/compare?a=${encodeURIComponent(name)}&b=${encodeURIComponent(other)}&boons=${boons}`);
      const labels = r.curve.map((c) => c.boon_level);
      const two = (ka, kb) => [{ name, color: C.you, values: r.curve.map((c) => c[ka]) }, { name: other, color: C.them, values: r.curve.map((c) => c[kb]) }];
      const opts = { xTitle: "Boons", height: 170, tipTitle: (i) => `${labels[i]} boons` };
      versus.replaceChildren(h("div.chart-title", {}, "Base gun DPS by boons"), lineChart(labels, two("hero_a_dps", "hero_b_dps"), opts),
        h("div.chart-title", {}, "HP by boons"), lineChart(labels, two("hero_a_hp", "hero_b_hp"), { ...opts, decimals: 0 }));
    } catch (e) { versus.replaceChildren(h("p.bad", {}, e.message)); }
  };
  const picker = heroSelect(name, (v) => { name = v; drawHero(); });
  main.replaceChildren(h("div.grid2", {},
    h("div.card", {}, h("div.row", {}, h("label.field", {}, "Hero", picker)), detail),
    h("div", {},
      h("div.card", {}, h("h2", {}, "Compare with"), h("div.row", {}, h("label.field", {}, "Hero", heroSelect(other, (v) => { other = v; drawVersus(); }))), versus),
      h("div.card", { style: "margin-top:14px" }, h("h2", {}, "Rankings"),
        h("div.row", { style: "align-items:flex-end;margin-bottom:6px" },
          h("label.field", {}, "Stat", h("select", { onchange: (e) => { stat = e.target.value; drawRanks(); } }, S.catalog.rank_stats.map((s) => h("option", { value: s }, s.replace(/_/g, " "))))),
          numberField("Boons", boons, (n) => { boons = Math.max(0, n); drawRanks(); drawVersus(); }, { min: 0, max: 50 })), ranks))));
  drawHero(); drawRanks();
}

// ── Patch notes tab ──────────────────────────────────────────────
async function renderPatchesTab(main) {
  const out = h("div"), picker = h("select");
  const show = (r) => {
    let filter = "all";
    const body = h("div");
    const draw = () => body.replaceChildren(table(["Change", "Status", "Current", "Notes"], r.entries
      .filter((e) => filter === "all" || e.status === filter || (filter === "manual_review" && e.status === "not_modeled"))
      .map((e) => [e.change.raw_line, h("span.status-" + e.status, {}, e.status.replace(/_/g, " ")), e.current_value.length > 40 ? e.current_value.slice(0, 40) + "…" : e.current_value, e.notes])));
    out.replaceChildren(h("p", {}, h("b", {}, `Patch ${r.date}`), ` — ${r.total} changes: `, h("span.good", {}, `${r.counts.already_applied} already in data`), ", ",
      h("span.gold", {}, `${r.counts.needs_update} differ from data`), ", ", h("span.muted", {}, `${r.counts.manual_review} need manual review`),
      r.url ? [" · ", h("a", { href: r.url, target: "_blank", rel: "noopener" }, "forum thread")] : null),
      h("div.row", { style: "margin-bottom:6px" }, h("label.field", {}, "Show", h("select", { onchange: (e) => { filter = e.target.value; draw(); } },
        [["all", "All changes"], ["needs_update", "Differs from data"], ["already_applied", "Already in data"], ["manual_review", "Manual review"]].map(([v, l]) => h("option", { value: v }, l))))), body);
    draw();
  };
  const load = async (date) => { busy(out); try { show(await api("/api/patches/" + encodeURIComponent(date))); } catch (e) { out.replaceChildren(h("p.bad", {}, e.message)); } };
  const fetchLatest = async (btn) => {
    btn.disabled = true;
    try { const r = await api("/api/patches/latest", {}); toast(`Fetched patch ${r.date}.`, "ok"); await renderPatchesTab(main); }
    catch (e) { fail(e); btn.disabled = false; }
  };
  main.replaceChildren(h("div.card", {}, h("h2", {}, "Patch notes vs. loaded data"),
    h("div.row", { style: "align-items:flex-end;margin-bottom:8px" }, h("label.field", {}, "Saved patch", picker), h("button", { onclick: (e) => fetchLatest(e.target) }, "Fetch latest from forum")), out));
  try {
    const { patches } = await api("/api/patches");
    picker.replaceChildren(...patches.map((p) => h("option", { value: p }, p)));
    picker.addEventListener("change", () => load(picker.value));
    if (patches.length) load(patches[0]); else out.replaceChildren(h("p.muted", {}, "No saved patches. Fetch the latest from the forum."));
  } catch (e) { out.replaceChildren(h("p.bad", {}, e.message)); }
}

// ── Settings tab ─────────────────────────────────────────────────
function renderSettingsTab(main) {
  const st = S.settings;
  const changed = () => { persist(); S.simScores = null; refreshBuild(); };
  const pctField = (label, key, max = 100, step = 5) => numberField(label, Math.round(st[key] * 100), (n) => { st[key] = Math.max(0, Math.min(max, n)) / 100; changed(); }, { min: 0, max, step });
  const check = (label, key) => h("label.check", {}, h("input", { type: "checkbox", checked: st[key], onchange: (e) => { st[key] = e.target.checked; changed(); } }), label);
  let hero = S.build.hero;
  const abilityBox = h("div");
  const drawAbilities = () => {
    const x = S.heroes[hero];
    const disabled = new Set(st.disabled_abilities[hero] || []);
    const order = st.ability_priority[hero] || [];
    abilityBox.replaceChildren(...x.abilities.map((a, i) => {
      const usable = a.base_damage > 0 && a.cooldown > 0;
      return h("label.check", { style: "padding:3px 0" }, h("input", { type: "checkbox", checked: usable && !disabled.has(i), disabled: !usable, onchange: (e) => {
        if (e.target.checked) disabled.delete(i); else disabled.add(i);
        st.disabled_abilities[hero] = [...disabled]; changed();
      } }), img(a.image_url, null, { style: "width:24px;height:24px" }), `${i + 1}. ${a.name}`, usable ? null : h("span.muted.small", {}, "(no damage or cooldown)"));
    }), h("label.field", { style: "margin-top:6px" }, "Cast order (ability numbers, e.g. 1, 3, 2, 4)", h("input", { type: "text", value: order.map((i) => i + 1).join(", "), placeholder: "default order",
      onchange: (e) => {
        const idx = e.target.value.split(",").map((s) => parseInt(s, 10) - 1).filter((n) => n >= 0 && n < x.abilities.length);
        if (idx.length) st.ability_priority[hero] = idx; else delete st.ability_priority[hero];
        changed();
      } })));
  };
  main.replaceChildren(h("div.grid2", {},
    h("div.card", {}, h("h2", {}, "Combat assumptions"),
      h("div.row", {}, numberField("Fight length (s)", st.duration, (n) => { st.duration = Math.max(1, Math.min(120, n)); changed(); }, { min: 1, max: 120 }),
        pctField("Accuracy %", "accuracy"), pctField("Headshot %", "headshot_rate"), numberField("Distance (m)", st.distance, (n) => { st.distance = Math.max(0, n); changed(); }, { min: 0, max: 200 })),
      h("p.muted.small", {}, "Accuracy and headshots drive realistic DPS, matchups, the simulation and Monte Carlo. Headshots use each hero’s own multiplier."),
      h("h3", {}, "Uptime"), h("div.row", {}, pctField("Weapon %", "weapon_uptime"), pctField("Abilities %", "ability_uptime", 200, 10), pctField("Active items %", "active_item_uptime", 200, 10)),
      h("h3", {}, "Simulation"), check("Defender fights back (bidirectional)", "bidirectional"), check("Heavy melee during reload", "melee_after_reload"), check("Melee cancels the reload (extends it)", "reload_cancel_melee"),
      h("h3", {}, "Conditional item stats"), h("p.muted.small", {}, "Count stats that need a trigger (on hit, on active use, …)."),
      check("On-hit shred (resist reduction)", "cond_shred"), check("Weapon bonuses (damage, fire rate, ammo)", "cond_weapon"), check("Spirit bonuses (spirit power, cooldowns)", "cond_spirit"),
      check("Defensive bonuses (resists, shields, HP)", "cond_defense"), check("Sustain bonuses (lifesteal, regen)", "cond_sustain"),
      h("div.row", { style: "margin-top:12px" }, h("button", { onclick: () => { S.settings = clone(S.catalog.default_settings); changed(); renderSettingsTab(main); toast("Settings reset."); } }, "Reset to defaults"))),
    h("div.card", {}, h("h2", {}, "Abilities used in simulations"), h("div.row", {}, h("label.field", {}, "Hero", heroSelect(hero, (v) => { hero = v; drawAbilities(); }))), abilityBox),
    h("div.card", {}, h("h2", {}, "Custom values for utility items"),
      h("p.muted.small", {}, "The simulator cannot model stuns, mobility or immunity. Give those items a DPS- or EHP-equivalent value to include them in simulation-based item sorting."),
      table(["Item", "Effect", { label: "DPS", num: true }, { label: "EHP", num: true }], S.catalog.utility_items.map((u) => {
        const f = (map, max) => h("input", { type: "number", min: 0, max, style: "width:70px", value: st[map][u.name] || 0, onchange: (e) => {
          const n = Math.max(0, Number(e.target.value) || 0);
          if (n) st[map][u.name] = n; else delete st[map][u.name];
          changed();
        } });
        return [h("span.row", {}, itemIcon(u.name, { style: "width:22px;height:22px" }), u.name), h("span.muted.small", {}, u.description), f("custom_item_dps", 500), f("custom_item_ehp", 5000)];
      })))));
  drawAbilities();
}

// ── Shell ────────────────────────────────────────────────────────
const RENDER = { "Build": renderBuildTab, "Analysis": renderAnalysisTab, "Simulation": renderSimulationTab, "Compare": renderCompareTab,
  "Saved Builds": renderSavedTab, "Heroes": renderHeroesTab, "Patch Notes": renderPatchesTab, "Settings": renderSettingsTab };
function renderTabs() {
  $("#tabs").replaceChildren(...TABS.map((t) => h("button", { role: "tab", "aria-selected": String(S.ui.tab === t), onclick: () => switchTab(t) }, t)));
}
function renderTab() {
  hideTip();
  (RENDER[S.ui.tab] || renderBuildTab)($("#main"));
}
function switchTab(tab) {
  S.ui.tab = tab;
  persist();
  renderTabs();
  renderTab();
}
function dataInfo() {
  const c = S.catalog, age = c.cache_age_seconds;
  const when = age == null ? "" : age < 3600 ? "updated just now" : age < 86400 ? `updated ${Math.round(age / 3600)}h ago` : `updated ${Math.round(age / 86400)} days ago`;
  $("#data-info").textContent = `${c.heroes.length} heroes · ${c.items.length} items · data ${when} · v${c.version}`;
}
async function loadCatalog() {
  S.catalog = await api("/api/catalog");
  S.heroes = Object.fromEntries(S.catalog.heroes.map((x) => [x.name, x]));
  S.items = Object.fromEntries(S.catalog.items.map((x) => [x.name, x]));
  dataInfo();
}
function sanitizeState() {
  if (!S.heroes[S.build.hero]) S.build.hero = S.catalog.heroes[0].name;
  S.build.items = (S.build.items || []).filter((n) => S.items[n]);
  S.build.ability_upgrades = S.build.ability_upgrades || {};
  S.build.extra_souls = Math.max(0, Number(S.build.extra_souls) || 0);
  S.settings = { ...clone(S.catalog.default_settings), ...(S.settings || {}) };
  for (const k of ["disabled_abilities", "ability_priority", "custom_item_dps", "custom_item_ehp"]) if (typeof S.settings[k] !== "object" || !S.settings[k]) S.settings[k] = {};
  S.defender.items = (S.defender.items || []).filter((n) => S.items[n]);
  if (!TABS.includes(S.ui.tab)) S.ui.tab = "Build";
}

$("#btn-refresh").addEventListener("click", async (e) => {
  e.target.disabled = true;
  toast("Refreshing data from the Deadlock API…");
  try {
    const r = await api("/api/refresh", {});
    await loadCatalog();
    sanitizeState();
    toast(`Refreshed: ${r.summary.heroes} heroes, ${r.summary.items} items.`, "ok");
    renderTab(); refreshBuild();
  } catch (err) { fail(err); }
  e.target.disabled = false;
});
$("#btn-feedback").addEventListener("click", () => {
  const cat = h("select", {}, ["Bug", "Suggestion", "Other"].map((c) => h("option", {}, c)));
  const text = h("textarea", { rows: 5, placeholder: "What happened? What did you expect?", maxlength: 2000 });
  openDialog("Bug report / suggestion", [h("label.field", {}, "Category", cat), h("label.field", { style: "margin-top:8px" }, "Description", text)], [
    h("button", { onclick: () => $("#dialog").close() }, "Cancel"),
    h("button.primary", { onclick: async () => {
      try { await api("/api/feedback", { category: cat.value, text: text.value }); $("#dialog").close(); toast("Thank you! Your feedback has been recorded.", "ok"); } catch (e) { fail(e); }
    } }, "Submit")]);
});
$("#btn-help").addEventListener("click", () => openDialog("Keyboard shortcuts", [
  [["/", "Search items"], ["Ctrl+Z", "Undo build change"], ["Ctrl+Shift+Z", "Redo"], ["Alt+1 … Alt+8", "Switch tabs"], ["Esc", "Close dialogs"]]
    .map(([k, d]) => h("div.line", {}, h("span", {}, d), h("kbd", {}, k)))]));
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  if (e.key === "/" && !typing && !$("#dialog").open) { e.preventDefault(); if (S.ui.tab !== "Build") switchTab("Build"); $("#shop-search").focus(); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
  else if (e.altKey && /^[1-8]$/.test(e.key)) { e.preventDefault(); switchTab(TABS[+e.key - 1]); }
});
window.addEventListener("hashchange", () => { const m = location.hash.match(/^#b=(.+)$/); if (m) loadCode(decodeURIComponent(m[1])); });

(async function init() {
  try {
    await loadCatalog();
    const saved = store.get(STATE_KEY, null);
    if (saved) { Object.assign(S.build, saved.build || {}); S.settings = saved.settings || {}; Object.assign(S.defender, saved.defender || {}); Object.assign(S.ui, saved.ui || {}); }
    sanitizeState();
    renderTabs();
    renderTab();
    const m = location.hash.match(/^#b=(.+)$/);
    if (m) await loadCode(decodeURIComponent(m[1]), true); else refreshBuild();
  } catch (e) {
    $("#main").replaceChildren(h("p.bad.pad", {}, "Could not load simulator data: " + e.message));
  }
})();
