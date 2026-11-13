/** Shared week-calendar helpers for admin RDN + Buy Request tabs. */

export const WINDOWS = ["10:00", "14:00", "18:00"];

export function pad2(value) {
  return String(value).padStart(2, "0");
}

export function kyivTodayIso() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export function addDaysIso(iso, days) {
  const [year, month, day] = iso.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1, day + days));
  return next.toISOString().slice(0, 10);
}

export function mondayOnOrBefore(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  const dow = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  const back = dow === 0 ? 6 : dow - 1;
  return addDaysIso(iso, -back);
}

export function bcp47(locale) {
  const map = {
    uk: "uk-UA",
    es: "es-ES",
    de: "de-DE",
    pl: "pl-PL",
    fr: "fr-FR",
    cs: "cs-CZ",
    nl: "nl-NL",
    bg: "bg-BG",
  };
  return map[locale] || "en-GB";
}

/** Slot text from the API (`30.10.2026, 14:00`) or an ISO id (`2026-10-30T14:00`). */
export function parseSlotLabel(label) {
  const text = String(label || "").trim();
  let match = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[,\s]+(\d{1,2}):(\d{2}))?/);
  if (match) {
    const time = match[4] != null ? `${pad2(Number(match[4]))}:${pad2(Number(match[5]))}` : null;
    return {
      iso: `${match[3]}-${pad2(Number(match[2]))}-${pad2(Number(match[1]))}`,
      time,
    };
  }
  match = text.match(/^(\d{4}-\d{2}-\d{2})(?:[T\s](\d{2}):(\d{2}))?/);
  if (!match) return null;
  return {
    iso: match[1],
    time: match[2] != null ? `${match[2]}:${match[3]}` : null,
  };
}

export function weekdayShort(iso, locale) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(bcp47(locale), {
    weekday: "short",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

export function weekRangeLabel(startIso, locale) {
  const endIso = addDaysIso(startIso, 6);
  const fmt = new Intl.DateTimeFormat(bcp47(locale), {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  });
  const startLabel = fmt.format(new Date(`${startIso}T00:00:00Z`));
  const endLabel = fmt.format(new Date(`${endIso}T00:00:00Z`));
  const startYear = startIso.slice(0, 4);
  const endYear = endIso.slice(0, 4);
  if (startYear === endYear) return `${startLabel} – ${endLabel} ${startYear}`;
  return `${startLabel} ${startYear} – ${endLabel} ${endYear}`;
}

/**
 * @param {Array<{ id: string, slot_label?: string, calendar_group?: string, kind?: string }>} items
 * @param {string[]} weekDays
 */
export function groupEventsBySlot(items, weekDays) {
  const placed = new Map();
  const unscheduled = [];
  const visible = new Set(weekDays);
  items.forEach((row) => {
    const parsed = parseSlotLabel(row.slot_label);
    if (!parsed?.time || !visible.has(parsed.iso)) {
      if (!parsed?.time) unscheduled.push(row);
      return;
    }
    const key = `${parsed.iso}|${parsed.time}`;
    const list = placed.get(key) || [];
    list.push(row);
    placed.set(key, list);
  });
  return { bySlot: placed, loose: unscheduled };
}

export function timesFromSlots(bySlot) {
  const extra = [];
  bySlot.forEach((_rows, key) => {
    const time = key.split("|")[1];
    if (time && !WINDOWS.includes(time)) extra.push(time);
  });
  return [...WINDOWS, ...extra].sort();
}

/** consultation | station | bess */
export function calendarGroupOf(row) {
  if (row.calendar_group === "station" || row.calendar_group === "bess" || row.calendar_group === "consultation") {
    return row.calendar_group;
  }
  if (row.kind === "station") return "station";
  if (row.kind === "bess" || row.kind === "bess_discount") return "bess";
  return "consultation";
}
