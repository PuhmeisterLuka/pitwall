// pitwall dashboard: pick a race, see the official result merged with OpenF1 timing.

import { ApiError, SOURCE_NAMES, api } from "./api.js";
import { COMPOUNDS, compound, lapChart, seriesColour, strategyChart } from "./charts.js";
import { h, icon } from "./dom.js";
import { ago, clock, gap, localStart, plural, raceDay } from "./format.js";

const FIRST_SEASON = 1950;
const OPENF1_FIRST_SEASON = 2023;
const MAX_PICKS = 3;
const TOP_STANDINGS = 10;
const OUTCOME_LABELS = { retired: "DNF", not_classified: "NC", disqualified: "DSQ", did_not_start: "DNS" };

const $ = (selector) => document.querySelector(selector);
const ui = {
  race: $("#race"),
  season: $("#season"),
  round: $("#round"),
  prev: $("#prev"),
  next: $("#next"),
  status: $("#status"),
};
const state = {
  season: null,
  round: null,
  events: [],
  view: null, // the race view from the API
  standings: null, // the standings view, or the Error that stopped it
  picks: new Map(), // driver code -> colour slot on the lap chart
  views: { strategy: "chart", laps: "chart" },
  charts: {}, // chart name -> stop function
};
let loads = 0; // each load takes a ticket; a stale ticket drops its result

const today = () => new Date().toISOString().slice(0, 10);
const thisYear = () => Number(today().slice(0, 4));
const hasRun = (event) => event.date < today();
const hasLapTimes = (entry) => entry.lap_times_s.some((time) => time != null);

// ---------------------------------------------------------------------------
// Loading and navigation

async function load(target, { push = false } = {}) {
  const ticket = ++loads;
  ui.race.classList.add("is-loading");
  try {
    const season = target.season ?? thisYear();
    if (season !== state.season) {
      const { events } = await api.season(season);
      if (ticket !== loads) return;
      Object.assign(state, { season, events });
      fillRounds();
    }
    const round = target.round ?? state.events.filter(hasRun).at(-1)?.round;
    if (round == null) {
      // A season that hasn't started yet: show the last one instead.
      if (target.season == null) return load({ season: season - 1, round: null }, { push });
      throw new ApiError(404, `No race in ${season} has been run yet.`);
    }
    state.round = round;
    syncControls();
    history[push ? "pushState" : "replaceState"](null, "", `?season=${season}&round=${round}`);

    const [race, standings] = await Promise.allSettled([
      api.race(season, round),
      api.standings(season, round),
    ]);
    if (ticket !== loads) return;
    if (race.status === "rejected") throw race.reason;
    state.view = race.value;
    state.standings = standings.status === "fulfilled" ? standings.value : standings.reason;
    state.picks = defaultPicks(race.value.report.entries);
    render();
    ui.status.textContent = `Showing the ${race.value.report.event.name} ${season}.`;
  } catch (error) {
    if (ticket === loads) showError(error, () => load(target));
  } finally {
    if (ticket === loads) ui.race.classList.remove("is-loading");
  }
}

const go = (season, round) => load({ season, round }, { push: true });

function fromUrl() {
  const params = new URLSearchParams(location.search);
  const number = (key) => {
    const value = Number(params.get(key));
    return params.has(key) && Number.isInteger(value) ? value : null;
  };
  return { season: number("season"), round: number("round") };
}

function fillSeasons() {
  const seasons = Array.from({ length: thisYear() - FIRST_SEASON + 1 }, (_, i) => thisYear() - i);
  ui.season.replaceChildren(...seasons.map((season) => h("option", { value: season }, String(season))));
}

function fillRounds() {
  ui.round.replaceChildren(...state.events.map((event) => h(
    "option",
    { value: event.round, disabled: !hasRun(event) },
    `${event.round} · ${event.name}${hasRun(event) ? "" : " (upcoming)"}`,
  )));
}

/** The raced rounds right before and after the one on screen. */
function neighbours() {
  const rounds = state.events.filter(hasRun).map((event) => event.round);
  return {
    prev: rounds.filter((round) => round < state.round).at(-1),
    next: rounds.find((round) => round > state.round),
  };
}

function syncControls() {
  ui.season.value = state.season;
  ui.round.value = state.round;
  const { prev, next } = neighbours();
  ui.prev.disabled = prev == null;
  ui.next.disabled = next == null;
}

function step(direction) {
  const round = neighbours()[direction];
  if (round != null) go(state.season, round);
}

// ---------------------------------------------------------------------------
// Rendering

function render() {
  const { report, sources } = state.view;
  const strategy = strategySection(report, sources);
  const parts = [
    hero(report, sources),
    podium(report.entries),
    notes(report.notes),
    classification(report.entries),
    strategy.el,
    h("section", { class: "section", id: "laps", "aria-labelledby": "laps-title" }),
    standingsSection(state.standings, report.entries),
  ];
  ui.race.replaceChildren(...parts.filter(Boolean)); // podium and notes are null when there's nothing to show
  mountChart("strategy", strategy.mount);
  renderLaps();
}

function mountChart(name, mount) {
  state.charts[name]?.();
  state.charts[name] = mount?.();
}

function showError(error, retry) {
  Object.keys(state.charts).forEach((name) => mountChart(name, null));
  const final = error instanceof ApiError && [404, 422].includes(error.status); // retrying won't change these
  ui.race.replaceChildren(h("div", { class: `notice ${final ? "" : "is-error"}` },
    h("p", {}, h("b", {}, final ? "Nothing to show. " : "That didn't load. "), error.message ?? String(error)),
    !final && h("button", { class: "btn more", type: "button", onclick: retry }, "Try again"),
  ));
}

function hero({ event, weather }, sources) {
  const when = event.starts_at ? `Lights out ${localStart(event.starts_at)}.` : `${raceDay(event.date)}.`;
  return h("section", { class: "hero", "aria-labelledby": "race-title" },
    h("p", { class: "eyebrow mono" }, `Round ${event.round} · ${event.season} season`),
    h("h1", { id: "race-title" }, event.name),
    h("p", { class: "lede" }, `${event.circuit}, ${event.locality}, ${event.country}. ${when}`),
    h("ul", { class: "chips", "aria-label": "Conditions and data sources" },
      weatherChips(weather), sourceChips(sources)),
  );
}

function weatherChips(weather) {
  if (!weather) return null;
  const range = ({ low, high }) => {
    const [a, b] = [Math.round(low), Math.round(high)];
    return a === b ? `${a} °C` : `${a}–${b} °C`;
  };
  return [
    h("li", { class: "chip" }, icon("thermometer"), `Air ${range(weather.air_c)} · track ${range(weather.track_c)}`),
    h("li", { class: "chip" }, icon(weather.rain ? "rain" : "sun"), weather.rain ? "Rain during the race" : "Dry"),
  ];
}

/** One chip per upstream: cached, live, a stale copy, or unavailable. */
function sourceChips(sources) {
  return Object.entries(sources).map(([name, source]) => {
    const ok = source.status === "hit" || source.status === "miss";
    const label = {
      hit: () => `cached ${ago(source.fetched_at)}`,
      miss: () => "live",
      stale: () => `offline, copy from ${ago(source.fetched_at)}`,
      error: () => "unavailable",
    }[source.status]();
    return h("li", { class: `chip ${ok ? "is-ok" : "is-warn"}`, title: source.error },
      icon(ok ? "check" : "alert"), `${SOURCE_NAMES[name] ?? name} · ${label}`);
  });
}

function podium(entries) {
  const top = entries.filter((entry) => entry.outcome === "finished").slice(0, 3);
  if (!top.length) return null;
  return h("ol", { class: "podium", "aria-label": "Podium" }, top.map((entry, i) => h(
    "li",
    { class: `tile ${i ? "" : "first"}` },
    h("span", { class: "place" }, `P${i + 1}`),
    h("span", { class: "who" }, teamDot(entry.driver), h("span", {}, entry.driver.name)),
    h("span", { class: "how mono" }, `${entry.driver.team} · ${resultText(entry)}`),
  )));
}

function notes(list) {
  if (!list.length) return null;
  return h("aside", { class: "notes", "aria-label": "Data notes" }, icon("info"), h("div", {},
    h("p", {}, h("b", {}, "Some timing data is missing")),
    h("ul", {}, list.map((note) => h("li", {}, note))),
  ));
}

// ---------------------------------------------------------------------------
// Classification

function classification(entries) {
  const fastest = entries.find((entry) => entry.fastest_lap?.rank === 1);
  return h("section", { class: "section", "aria-labelledby": "results-title" },
    sectionHead("results-title", "Classification", "The official result, with team colours and tyres from OpenF1."),
    h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {},
        th("Pos"), th("Driver"), th("Team", "hide-sm"), th("Grid", "hide-sm right"), th("Laps", "hide-sm right"),
        th("Time / gap", "right"), th("Pts", "right"), th("Fastest lap", "hide-sm right"), th("Tyres", "hide-sm"),
      )),
      h("tbody", {}, entries.map((entry) => resultRow(entry, entry === fastest))),
    )),
  );
}

function resultRow(entry, isFastest) {
  const { driver } = entry;
  const finished = entry.outcome === "finished";
  const position = finished ? String(entry.position) : OUTCOME_LABELS[entry.outcome];
  return h("tr", {},
    h("td", { class: `pos ${finished ? "" : "out"}` }, position),
    h("td", {}, driverCell(driver)),
    h("td", { class: "hide-sm" }, driver.team),
    h("td", { class: "hide-sm right num" }, gridCell(entry)),
    h("td", { class: "hide-sm right num" }, String(entry.laps_completed)),
    h("td", { class: "right num" }, resultText(entry)),
    h("td", { class: "right num" }, points(entry.points)),
    h("td", { class: "hide-sm right num" }, fastestCell(entry, isFastest)),
    h("td", { class: "hide-sm" }, tyreDiscs(entry.stints)),
  );
}

function resultText(entry) {
  if (entry.outcome !== "finished") return entry.status;
  if (entry.gap_s === 0) return clock(entry.race_time_s);
  if (entry.gap_s != null) return gap(entry.gap_s);
  if (entry.laps_down) return `+${plural(entry.laps_down, "lap")}`;
  return entry.status;
}

function gridCell(entry) {
  if (entry.grid == null) return "Pit lane";
  const change = entry.outcome === "finished" ? entry.grid - entry.position : 0;
  if (!change) return String(entry.grid);
  const verb = change > 0 ? "gained" : "lost";
  const places = Math.abs(change);
  return [
    String(entry.grid),
    h("span", { class: `change ${change > 0 ? "gain" : "muted"}`, title: `${verb} ${plural(places, "place")}` },
      icon(change > 0 ? "up" : "down", 12), h("span", { class: "sr-only" }, verb), String(places)),
  ];
}

function fastestCell(entry, isFastest) {
  if (!entry.fastest_lap) return "–";
  return [
    clock(entry.fastest_lap.time_s),
    isFastest && h("span", { class: "tag", title: "Fastest lap of the race" }, "Fastest"),
  ];
}

function tyreDiscs(stints) {
  if (!stints.length) return "–";
  const tyres = stints.map((stint) => compound(stint.compound));
  return h("span", { class: "tyres" },
    h("span", { class: "sr-only" }, tyres.map((tyre) => tyre.name).join(", ")),
    tyres.map((tyre) => h(
      "span", { class: `tyre ${tyre.className}`, "aria-hidden": "true", title: tyre.name }, tyre.letter,
    )),
  );
}

// ---------------------------------------------------------------------------
// Tyre strategy

function strategySection(report, sources) {
  const rows = report.entries.filter((entry) => entry.stints.length);
  const head = (...actions) => sectionHead("strategy-title", "Tyre strategy",
    "Each bar is one driver's race, split into stints. The gaps are pit stops.", ...actions);
  const el = h("section", { class: "section", "aria-labelledby": "strategy-title" });
  if (!rows.length) {
    el.append(head(), timingMissing(report, sources, "tyre stints"));
    return { el };
  }
  const block = chartBlock("strategy", {
    label: "Tyre strategy chart. Arrow keys move between drivers and stints; the table view lists every stint.",
    legend: compoundLegend(rows),
    table: strategyTable(rows),
    draw: (host) => strategyChart(host, rows),
  });
  el.append(head(block.toggle), block.figure, block.table);
  return { el, mount: block.mount };
}

function compoundLegend(rows) {
  const used = new Set(rows.flatMap((entry) => entry.stints.map((stint) => compound(stint.compound).name)));
  const tyres = Object.keys(COMPOUNDS).map(compound).filter((tyre) => used.has(tyre.name));
  return h("ul", { class: "legend", "aria-label": "Compounds" }, tyres.map((tyre) => h("li", {},
    h("span", { class: `key-rect ${tyre.className}` }), `${tyre.name} (${tyre.letter})`)));
}

function strategyTable(rows) {
  const stints = (entry) => entry.stints
    .map((stint) => `${compound(stint.compound).name} ${stint.first_lap}–${stint.last_lap}`)
    .join(" · ");
  return h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {}, th("Driver"), th("Stints"), th("Stops", "right"))),
    h("tbody", {}, rows.map((entry) => h("tr", {},
      h("td", {}, driverCell(entry.driver)),
      h("td", {}, stints(entry)),
      h("td", { class: "right num" }, entry.pit_stops.length ? String(entry.pit_stops.length) : "–"),
    ))),
  ));
}

// ---------------------------------------------------------------------------
// Lap times

function renderLaps(focusCode) {
  const { report, sources } = state.view;
  const section = $("#laps");
  const { children, mount } = lapsContent(report, sources);
  section.replaceChildren(...children);
  mountChart("laps", mount);
  if (focusCode) section.querySelector(`[data-code="${CSS.escape(focusCode)}"]`)?.focus();
}

function lapsContent(report, sources) {
  const series = report.entries.filter(hasLapTimes);
  const head = (...actions) => sectionHead("laps-title", "Lap times",
    "Pick up to three drivers. Pit stops and safety car laps run off the top.", ...actions);
  if (!series.length) return { children: [head(), timingMissing(report, sources, "lap times")] };
  const block = chartBlock("laps", {
    label: "Lap time chart. Left and right arrow keys move between laps; the table view lists every time.",
    legend: lapLegend(series),
    table: lapTable(series),
    draw: (host) => lapChart(host, series, state.picks),
  });
  return { children: [head(block.toggle), picker(series), block.figure, block.table], mount: block.mount };
}

const defaultPicks = (entries) => new Map(
  entries.filter(hasLapTimes).slice(0, MAX_PICKS).map((entry, slot) => [entry.driver.code, slot]),
);

/** A driver keeps their colour while picked; a new pick takes the lowest free slot. */
function togglePick(code) {
  const picks = new Map(state.picks);
  if (picks.has(code)) picks.delete(code);
  else picks.set(code, [0, 1, 2].find((slot) => ![...picks.values()].includes(slot)));
  state.picks = picks;
  renderLaps(code);
}

function picker(series) {
  const full = state.picks.size >= MAX_PICKS;
  return h("div", { class: "picker", role: "group", "aria-label": "Drivers to highlight" }, series.map((entry) => {
    const { code } = entry.driver;
    const slot = state.picks.get(code);
    return h("button", {
      type: "button", class: "pick", "data-code": code, "aria-pressed": String(slot != null),
      disabled: slot == null && full, onclick: () => togglePick(code),
    }, h("span", { class: "key-line", style: { "--key": slot == null ? "transparent" : seriesColour(slot) } }), code);
  }));
}

function lapLegend(series) {
  return h("ul", { class: "legend", "aria-label": "Legend" },
    pickedOf(series).map((entry) => h("li", {},
      h("span", { class: "key-line", style: { "--key": seriesColour(state.picks.get(entry.driver.code)) } }),
      `${entry.driver.code} · ${entry.driver.name}`)),
    h("li", {}, h("span", { class: "key-line context" }), "Everyone else"),
  );
}

function lapTable(series) {
  const picked = pickedOf(series);
  if (!picked.length) return h("p", { class: "empty" }, "Pick a driver above to list their lap times.");
  const laps = Math.max(...picked.map((entry) => entry.lap_times_s.length));
  const time = (entry, i) => (entry.lap_times_s[i] == null ? "–" : clock(entry.lap_times_s[i]));
  return h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {}, th("Lap"), picked.map((entry) => th(entry.driver.code, "right")))),
    h("tbody", {}, Array.from({ length: laps }, (_, i) => h("tr", {},
      h("td", { class: "num" }, String(i + 1)),
      picked.map((entry) => h("td", { class: "right num" }, time(entry, i))),
    ))),
  ));
}

const pickedOf = (series) => series
  .filter((entry) => state.picks.has(entry.driver.code))
  .sort((a, b) => state.picks.get(a.driver.code) - state.picks.get(b.driver.code));

// ---------------------------------------------------------------------------
// Standings

function standingsSection(view, entries) {
  const failed = view instanceof Error;
  const el = h("section", { class: "section", "aria-labelledby": "standings-title" },
    sectionHead("standings-title", "Championship", failed ? null : `Drivers' standings after round ${view.round}.`));
  if (failed) {
    el.append(h("p", { class: "empty" }, `The standings didn't load. ${view.message}`));
    return el;
  }
  const colours = new Map(entries.map((entry) => [entry.driver.code, entry.driver.team_colour]));
  const rows = view.standings.map((row) => h("tr", {},
    h("td", { class: "pos" }, row.position == null ? "–" : String(row.position)),
    h("td", {}, driverCell({ code: row.code, name: row.name, team_colour: colours.get(row.code) })),
    h("td", { class: "hide-sm" }, row.team),
    h("td", { class: "right num" }, points(row.points)),
    h("td", { class: "right num hide-sm" }, String(row.wins)),
  ));
  const body = h("tbody", {}, rows.slice(0, TOP_STANDINGS));
  el.append(h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {},
      th("Pos"), th("Driver"), th("Team", "hide-sm"), th("Pts", "right"), th("Wins", "right hide-sm"),
    )),
    body,
  )));
  if (rows.length > TOP_STANDINGS) {
    const more = h("button", { class: "btn more", type: "button" }, `Show all ${rows.length}`);
    more.addEventListener("click", () => {
      body.replaceChildren(...rows);
      more.remove();
    });
    el.append(more);
  }
  return el;
}

// ---------------------------------------------------------------------------
// Shared pieces

function sectionHead(id, title, blurb, ...actions) {
  return h("div", { class: "section-head" }, h("div", {}, h("h2", { id }, title), blurb && h("p", {}, blurb)), actions);
}

const th = (label, className) => h("th", { scope: "col", class: className }, label);

const points = (value) => (Number.isInteger(value) ? String(value) : value.toFixed(1));

function teamDot(driver) {
  const colour = driver.team_colour ?? "var(--line-strong)";
  return h("span", { class: "team-dot", "aria-hidden": "true", style: { "--dot": colour } });
}

function driverCell(driver) {
  return h("span", { class: "driver-cell" },
    teamDot(driver), h("b", {}, driver.code), h("span", { class: "muted hide-sm" }, driver.name));
}

/** A chart with its legend, the table twin and the switch between them. */
function chartBlock(name, { label, legend, table, draw }) {
  const host = h("div", { class: `chart ${name}`, tabindex: 0, "aria-label": label });
  const figure = h("figure", {}, legend, host);
  return { figure, table, toggle: viewToggle(name, figure, table), mount: () => draw(host) };
}

/** Chart or table; each section keeps its choice across redraws. */
function viewToggle(name, chart, table) {
  const modes = ["chart", "table"];
  const buttons = modes.map((mode) => h(
    "button", { type: "button", onclick: () => show(mode) }, mode === "chart" ? "Chart" : "Table",
  ));
  const control = h("div", { class: "segmented", role: "group", "aria-label": "Show as", style: { "--n": "2" } },
    h("span", { class: "segmented-thumb", "aria-hidden": "true" }), buttons);
  function show(mode) {
    state.views[name] = mode;
    buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(modes[i] === mode)));
    control.style.setProperty("--i", String(modes.indexOf(mode)));
    chart.hidden = mode !== "chart";
    table.hidden = mode !== "table";
  }
  show(state.views[name]);
  return control;
}

function timingMissing(report, sources, what) {
  let reason = `OpenF1 has no ${what} for this race.`;
  if (sources.openf1?.status === "error") {
    const why = sources.openf1.error;
    reason = `OpenF1 can't be read right now (${why}), so the ${what} are missing. `
      + "The official result above is complete.";
  } else if (report.event.season < OPENF1_FIRST_SEASON) {
    reason = `OpenF1's timing starts in ${OPENF1_FIRST_SEASON}, so this race has the official result only.`;
  }
  return h("p", { class: "empty" }, reason);
}

// ---------------------------------------------------------------------------

fillSeasons();
ui.season.addEventListener("change", () => go(Number(ui.season.value), null));
ui.round.addEventListener("change", () => go(state.season, Number(ui.round.value)));
ui.prev.addEventListener("click", () => step("prev"));
ui.next.addEventListener("click", () => step("next"));
addEventListener("popstate", () => load(fromUrl()));
load(fromUrl());
