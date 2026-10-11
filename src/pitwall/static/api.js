// Calls to the pitwall API. Failures come back as ApiError with a message you can show.

export const SOURCE_NAMES = { jolpica: "Jolpica", openf1: "OpenF1" };

export class ApiError extends Error {
  constructor(status, detail, source) {
    super(source ? `${SOURCE_NAMES[source] ?? source} didn't answer properly (${detail}).` : detail);
    this.status = status;
    this.source = source;
  }
}

async function getJson(path) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, "The pitwall server can't be reached.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    // FastAPI sends a rejected URL (422) as a list of problems; the reader needs one sentence.
    const detail = typeof body.detail === "string" ? body.detail : "That season or round isn't valid.";
    throw new ApiError(response.status, detail, body.source);
  }
  return body;
}

export const api = {
  season: (season) => getJson(`/api/seasons/${season}`),
  race: (season, round) => getJson(`/api/seasons/${season}/rounds/${round}`),
  standings: (season, round) => getJson(`/api/seasons/${season}/rounds/${round}/standings`),
};
