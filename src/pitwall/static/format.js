// Formatting for times, gaps and dates.

const pad = (n) => String(n).padStart(2, "0");

/** 106.653 -> "1:46.653", 4797.566 -> "1:19:57.566", 59.1 -> "59.100". */
export function clock(seconds, decimals = 3) {
  const scale = 10 ** decimals;
  const units = Math.round(seconds * scale); // round once, or 59.9996 comes out as "0:60.000"
  const fraction = units % scale;
  const whole = (units - fraction) / scale;
  const [hours, minutes, secs] = [Math.floor(whole / 3600), Math.floor((whole % 3600) / 60), whole % 60];
  const tail = decimals ? `.${String(fraction).padStart(decimals, "0")}` : "";
  if (hours) return `${hours}:${pad(minutes)}:${pad(secs)}${tail}`;
  if (minutes) return `${minutes}:${pad(secs)}${tail}`;
  return `${secs}${tail}`;
}

export const gap = (seconds) => `+${clock(seconds)}`;

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** How long ago an ISO timestamp was, in words. */
export function ago(iso, now = Date.now()) {
  const minutes = Math.round((now - Date.parse(iso)) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const startFormat = new Intl.DateTimeFormat(undefined, {
  weekday: "short", day: "numeric", month: "short", year: "numeric",
  hour: "numeric", minute: "2-digit", timeZoneName: "short",
});

/** "2024-07-28" (the race day as published) -> "Sun 28 Jul 2024". */
export const raceDay = (date) => dayFormat.format(new Date(`${date}T00:00:00Z`));

/** A UTC start as date and time in the reader's zone, so the day and the hour agree. */
export const localStart = (iso) => startFormat.format(new Date(iso));
