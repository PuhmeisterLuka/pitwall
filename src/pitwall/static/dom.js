// Tiny DOM builders. Children go in as text nodes, so API data can't inject HTML.

const SVG_NS = "http://www.w3.org/2000/svg";

export function h(tag, props = {}, ...children) {
  return build(document.createElement(tag), props, children);
}

export function s(tag, props = {}, ...children) {
  return build(document.createElementNS(SVG_NS, tag), props, children);
}

function build(el, props, children) {
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "style") {
      for (const [name, v] of Object.entries(value)) el.style.setProperty(name, v);
    } else if (key.startsWith("on")) {
      el.addEventListener(key.slice(2), value);
    } else {
      el.setAttribute(key, value === true ? "" : value);
    }
  }
  el.append(...children.flat(Infinity).filter((child) => child != null && child !== false));
  return el;
}

// Lucide-style 24px line icons, drawn at 16px.
const ICONS = {
  check: ["M20 6 9 17l-5-5"],
  alert: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
  info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 16v-4", "M12 8h.01"],
  thermometer: ["M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"],
  rain: ["M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2", "M16 14v6", "M8 14v6", "M12 16v6"],
  sun: [
    "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M12 2v2", "M12 20v2", "M2 12h2", "M20 12h2",
    "m4.93 4.93 1.41 1.41", "m17.66 17.66 1.41 1.41", "m6.34 17.66-1.41 1.41", "m19.07 4.93-1.41 1.41",
  ],
  up: ["m18 15-6-6-6 6"],
  down: ["m6 9 6 6 6-6"],
};

export function icon(name, size = 16) {
  return s(
    "svg",
    {
      width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
    },
    ICONS[name].map((d) => s("path", { d })),
  );
}
