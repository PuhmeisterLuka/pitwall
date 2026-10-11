// Two SVG charts: tyre strategy (stacked bars) and lap times (lines with a crosshair).
// Marks follow the dataviz specs: thin bars with 4px rounded ends, 2px lines, 2px surface gaps.

import { h, s } from "./dom.js";
import { clock, plural } from "./format.js";

export const COMPOUNDS = {
  SOFT: { letter: "S", name: "Soft", ink: "on-dark" },
  MEDIUM: { letter: "M", name: "Medium", ink: "on-dark" },
  HARD: { letter: "H", name: "Hard", ink: "on-dark" },
  INTERMEDIATE: { letter: "I", name: "Intermediate", ink: "on-light" },
  WET: { letter: "W", name: "Wet", ink: "on-wet" },
  UNKNOWN: { letter: "?", name: "Unknown", ink: "on-dark" },
};

export function compound(name) {
  const key = name in COMPOUNDS ? name : "UNKNOWN";
  return { ...COMPOUNDS[key], className: `c-${key.toLowerCase()}` };
}

export const seriesColour = (slot) => `var(--series-${slot + 1})`;

/** Draw now and again whenever the host's width changes. Returns a stop function. */
function responsive(host, draw) {
  let width = 0;
  const observer = new ResizeObserver(([entry]) => {
    const next = Math.floor(entry.contentRect.width);
    if (next && next !== width) draw((width = next));
  });
  observer.observe(host);
  return () => observer.disconnect();
}

const scale = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

/** A round step that splits `span` into about `count` parts. */
function niceStep(span, count) {
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * power).find((step) => step >= raw);
}

function ticks(from, to, step) {
  const out = [];
  for (let v = Math.ceil(from / step) * step; v <= to + 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/** Lap numbers along the bottom, optionally with vertical gridlines from `top`. */
function lapAxis(x, laps, bottom, top = null) {
  const step = niceStep(laps, 6);
  return s("g", { class: "grid" }, ticks(step, laps, step).map((lap) => [
    top != null && s("line", { x1: x(lap), x2: x(lap), y1: top, y2: bottom }),
    s("text", { x: x(lap), y: bottom + 16, "text-anchor": "middle" }, String(lap)),
  ]));
}

/** A bar whose right end is rounded and whose left end stays square on the baseline. */
function bar(x, y, w, height, radius) {
  const r = Math.min(radius, height / 2, w);
  if (!r) return `M${x},${y}h${w}v${height}h${-w}z`;
  return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${height - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${r - w}z`;
}

function tooltip(host) {
  const tip = h("div", { class: "tooltip", hidden: true });
  host.append(tip);
  return {
    show(x, y, title, rows) {
      tip.replaceChildren(h("p", { class: "tip-title" }, title), ...rows);
      tip.hidden = false;
      const right = x + 14 + tip.offsetWidth <= host.clientWidth;
      const left = right ? x + 14 : x - 14 - tip.offsetWidth;
      tip.style.translate = `${Math.max(0, left)}px ${Math.max(0, y - tip.offsetHeight / 2)}px`;
    },
    hide() {
      tip.hidden = true;
    },
  };
}

const tipRow = (key, value, label) => h("p", { class: "tip-row" }, key, h("b", {}, value), h("span", {}, label));

const pointerX = (svg, event) => event.clientX - svg.getBoundingClientRect().left;
const pointerY = (svg, event) => event.clientY - svg.getBoundingClientRect().top;

// ---------------------------------------------------------------------------
// Tyre strategy

const ROW = 22;
const BAR = 12;
const STRATEGY = { top: 4, right: 8, bottom: 26, left: 44 };

/** One bar per driver in finishing order, split into stints. Arrow keys walk the stints. */
export function strategyChart(host, entries) {
  const laps = Math.max(...entries.flatMap((e) => [e.laps_completed, ...e.stints.map((st) => st.last_lap)]));
  return responsive(host, (width) => drawStrategy(host, entries, laps, width));
}

function drawStrategy(host, entries, laps, width) {
  const m = STRATEGY;
  const height = m.top + entries.length * ROW + m.bottom;
  const x = scale(0, laps, m.left, width - m.right);
  const svg = s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  host.replaceChildren(svg);
  const tip = tooltip(host);

  svg.append(
    lapAxis(x, laps, height - m.bottom, m.top),
    s("line", { class: "baseline", x1: x(0), x2: x(0), y1: m.top, y2: height - m.bottom }),
  );
  entries.forEach((entry, row) => {
    const y = m.top + row * ROW + (ROW - BAR) / 2;
    svg.append(s("text", {
      class: "row-label", x: m.left - 10, y: y + BAR / 2, "text-anchor": "end", "dominant-baseline": "central",
    }, entry.driver.code));
    entry.stints.forEach((stint, i) => {
      const last = i === entry.stints.length - 1;
      const x0 = x(stint.first_lap - 1) + (i ? 1 : 0); // 2px surface gap between stints
      const w = Math.max(x(stint.last_lap) - (last ? 0 : 1) - x0, 1);
      const tyre = compound(stint.compound);
      const d = bar(x0, y, w, BAR, last ? 4 : 0);
      svg.append(s("path", { class: `seg ${tyre.className}`, d, "data-row": row, "data-stint": i }));
      if (w >= 16) {
        svg.append(s("text", {
          class: `seg-label ${tyre.ink}`, x: x0 + w / 2, y: y + BAR / 2,
          "text-anchor": "middle", "dominant-baseline": "central",
        }, tyre.letter));
      }
    });
  });

  let cursor = { row: 0, stint: 0 };
  const show = ({ row, stint: i }) => {
    const entry = entries[row];
    const stint = entry?.stints[i];
    svg.querySelector(".seg.is-active")?.classList.remove("is-active");
    host.classList.toggle("has-focus", Boolean(stint));
    if (!stint) return tip.hide();
    cursor = { row, stint: i };
    svg.querySelector(`.seg[data-row="${row}"][data-stint="${i}"]`).classList.add("is-active");
    const tyre = compound(stint.compound);
    const age = stint.tyre_age_at_start ? `${plural(stint.tyre_age_at_start, "lap")} old` : "new";
    const key = h("span", { class: `key-rect ${tyre.className}` });
    const length = plural(stint.last_lap - stint.first_lap + 1, "lap");
    tip.show(x((stint.first_lap - 1 + stint.last_lap) / 2), m.top + row * ROW + ROW / 2,
      `${entry.driver.code} · stint ${i + 1} of ${entry.stints.length}`, [
        tipRow(key, tyre.name, `laps ${stint.first_lap}–${stint.last_lap}`),
        h("p", { class: "tip-row muted" }, `${length} · fitted ${age}`),
      ]);
  };
  const hide = () => show({ row: -1, stint: -1 });

  // Hovering anywhere in a 22px row band counts, so you don't have to hit the 12px bar.
  svg.addEventListener("pointermove", (event) => {
    const row = Math.floor((pointerY(svg, event) - m.top) / ROW);
    const lap = (pointerX(svg, event) - m.left) / (width - m.left - m.right) * laps;
    const stint = entries[row]?.stints.findIndex((st) => lap >= st.first_lap - 1 && lap <= st.last_lap) ?? -1;
    show({ row, stint });
  });
  svg.addEventListener("pointerleave", hide);
  host.onfocus = () => show(cursor);
  host.onblur = hide;
  host.onkeydown = (event) => {
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (event.key === "Escape") return hide();
    if (!(event.key in moves)) return;
    event.preventDefault();
    const [dRow, dStint] = moves[event.key];
    const row = Math.min(Math.max(cursor.row + dRow, 0), entries.length - 1);
    const count = entries[row].stints.length;
    show({ row, stint: Math.min(Math.max(cursor.stint + dStint, 0), count - 1) });
  };
}

// ---------------------------------------------------------------------------
// Lap times

const LAPS = { top: 12, right: 48, bottom: 26, left: 56 };
const LAPS_HEIGHT = 300;

/**
 * Picked drivers as coloured lines over everyone else in grey. `picked` maps a driver code
 * to its colour slot, so a driver keeps its colour when others are added or removed.
 */
export function lapChart(host, entries, picked) {
  const laps = Math.max(...entries.map((e) => e.lap_times_s.length));
  const domain = lapDomain(entries);
  return responsive(host, (width) => drawLaps(host, entries, picked, laps, domain, width));
}

/** Fit the y axis to racing laps. Lap 1 and pit laps run off the top so they don't squash the rest. */
function lapDomain(entries) {
  const all = entries.flatMap((e) => e.lap_times_s.filter((t) => t != null));
  const racing = entries.flatMap((e) => {
    return e.lap_times_s.filter((t, i) => t != null && i > 0 && !pitLap(e, i + 1));
  });
  const times = (racing.length ? racing : all).sort((a, b) => a - b);
  const lo = times[0];
  const hi = times[Math.floor((times.length - 1) * 0.95)];
  const pad = Math.max(hi - lo, 1);
  return [lo - pad * 0.08, hi + pad * 0.3];
}

/** "in" or "out" when the car pitted around this lap. OpenF1 logs a stop on the lap the car came in. */
function pitLap(entry, lap) {
  if (entry.pit_stops.some((stop) => stop.lap === lap)) return "in";
  if (entry.pit_stops.some((stop) => stop.lap + 1 === lap)) return "out";
  return null;
}

function linePath(times, x, y) {
  let d = "";
  let drawing = false;
  times.forEach((t, i) => {
    if (t == null) {
      drawing = false; // a missing lap leaves a gap in the line
      return;
    }
    d += `${drawing ? "L" : "M"}${x(i + 1).toFixed(1)},${y(t).toFixed(1)}`;
    drawing = true;
  });
  return d;
}

const lastTimedLap = (times) => times.findLastIndex((t) => t != null) + 1;

let clipIds = 0;

function drawLaps(host, entries, picked, laps, [lo, hi], width) {
  const m = LAPS;
  const height = LAPS_HEIGHT;
  const bottom = height - m.bottom;
  const x = scale(1, laps, m.left, width - m.right);
  const y = scale(lo, hi, bottom, m.top);
  const svg = s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  host.replaceChildren(svg);
  const tip = tooltip(host);
  const slot = (entry) => picked.get(entry.driver.code);
  const isPicked = (entry) => picked.has(entry.driver.code);
  const clipId = `lap-clip-${++clipIds}`;
  const plot = { x: m.left, y: m.top, width: width - m.left - m.right, height: bottom - m.top };
  const line = (e, className, stroke) => s("path", { class: className, d: linePath(e.lap_times_s, x, y), stroke });

  const step = niceStep(hi - lo, 5);
  const decimals = step < 1 ? 1 : 0;
  svg.append(
    s("defs", {}, s("clipPath", { id: clipId }, s("rect", plot))),
    s("g", { class: "grid" }, ticks(lo, hi, step).map((t) => [
      s("line", { x1: m.left, x2: width - m.right, y1: y(t), y2: y(t) }),
      s("text", { x: m.left - 10, y: y(t), "text-anchor": "end", "dominant-baseline": "central" }, clock(t, decimals)),
    ])),
    lapAxis(x, laps, bottom),
    s("line", { class: "baseline", x1: m.left, x2: width - m.right, y1: bottom, y2: bottom }),
    s("g", { "clip-path": `url(#${clipId})` },
      entries.filter((e) => !isPicked(e)).map((e) => line(e, "line context")),
      entries.filter(isPicked).map((e) => line(e, "line", seriesColour(slot(e)))),
    ),
  );

  // End dots get a driver label when there's room; the legend names them either way.
  const ends = entries.filter(isPicked)
    .map((e) => ({ e, lap: lastTimedLap(e.lap_times_s) }))
    .filter(({ lap }) => lap)
    .map(({ e, lap }) => ({ e, cx: x(lap), cy: y(e.lap_times_s[lap - 1]) }))
    .filter(({ cy }) => cy >= m.top && cy <= bottom);
  const byHeight = [...ends].sort((a, b) => a.cy - b.cy);
  const roomy = byHeight.every((end, i) => i === 0 || end.cy - byHeight[i - 1].cy >= 14);
  for (const { e, cx, cy } of ends) {
    svg.append(s("circle", { class: "end-dot", cx, cy, r: 4, fill: seriesColour(slot(e)) }));
    if (roomy) {
      svg.append(s("text", { class: "end-label", x: cx + 9, y: cy, "dominant-baseline": "central" }, e.driver.code));
    }
  }

  const cross = s("line", { class: "crosshair", y1: m.top, y2: bottom, visibility: "hidden" });
  const hit = s("rect", { class: "lap-hit", ...plot });
  svg.append(cross, hit);

  let cursor = laps;
  const show = (lap) => {
    cursor = Math.min(Math.max(lap, 1), laps);
    cross.setAttribute("x1", x(cursor));
    cross.setAttribute("x2", x(cursor));
    cross.setAttribute("visibility", "visible");
    const rows = entries.filter(isPicked)
      .map((e) => ({ e, t: e.lap_times_s[cursor - 1], pit: pitLap(e, cursor) }))
      .sort((a, b) => (a.t ?? Infinity) - (b.t ?? Infinity))
      .map(({ e, t, pit }) => tipRow(
        h("span", { class: "key-line", style: { "--key": seriesColour(slot(e)) } }),
        t == null ? "–" : clock(t),
        pit ? `${e.driver.code} · pit ${pit}` : e.driver.code,
      ));
    const empty = h("p", { class: "tip-row muted" }, "Pick a driver to read their times");
    tip.show(x(cursor), m.top + 40, `Lap ${cursor}`, rows.length ? rows : [empty]);
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    tip.hide();
  };

  hit.addEventListener("pointermove", (event) => {
    show(Math.round((pointerX(svg, event) - m.left) / (width - m.left - m.right) * (laps - 1)) + 1);
  });
  hit.addEventListener("pointerleave", hide);
  host.onfocus = () => show(cursor);
  host.onblur = hide;
  host.onkeydown = (event) => {
    const moves = { ArrowLeft: cursor - 1, ArrowRight: cursor + 1, Home: 1, End: laps };
    if (event.key === "Escape") return hide();
    if (!(event.key in moves)) return;
    event.preventDefault();
    show(moves[event.key]);
  };
}
