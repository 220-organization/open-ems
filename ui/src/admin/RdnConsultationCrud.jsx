import { useCallback, useEffect, useMemo, useState } from "react";
import styles from "../AdminPage.module.css";

const KINDS = ["payment", "callback"];
const STATUSES = ["created", "SUCCESS", "FAILURE", "requested", "EXPIRED", "REVERSED"];
const WINDOWS = ["10:00", "14:00", "18:00"];

function pad2(value) {
  return String(value).padStart(2, "0");
}

function kyivTodayIso() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function addDaysIso(iso, days) {
  const [year, month, day] = iso.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1, day + days));
  return next.toISOString().slice(0, 10);
}

function mondayOnOrBefore(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  const dow = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  const back = dow === 0 ? 6 : dow - 1;
  return addDaysIso(iso, -back);
}

function bcp47(locale) {
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
function parseSlotLabel(label) {
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

function weekdayShort(iso, locale) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(bcp47(locale), {
    weekday: "short",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

function weekRangeLabel(startIso, locale) {
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

function apiBase() {
  return (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
}

function emptyDraft() {
  return {
    id: null,
    kind: "callback",
    name: "",
    phone: "",
    slot_label: "",
    amount_uah: "",
    status: "requested",
    description: "",
  };
}

function draftFromRow(row) {
  return {
    id: row.id,
    kind: row.kind || "callback",
    name: row.name || "",
    phone: row.phone || "",
    slot_label: row.slot_label || "",
    amount_uah: row.amount_uah == null ? "" : String(row.amount_uah),
    status: row.status || "created",
    description: row.description || "",
  };
}

function kindLabel(t, kind) {
  return kind === "callback" ? t("rdnAdminKindCallback") : t("rdnAdminKindPayment");
}

export default function RdnConsultationCrud({ t, token, locale = "uk" }) {
  const [items, setItems] = useState([]);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [weekStart, setWeekStart] = useState(() => mondayOnOrBefore(kyivTodayIso()));

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${apiBase()}/api/rdn-consultation/admin`, {
        headers: { token },
        cache: "no-store",
      });
      if (!response.ok) throw new Error("load");
      const data = await response.json();
      setItems(Array.isArray(data.items) ? data.items : []);
    } catch {
      setError(t("adminLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, token]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const amountRaw = String(draft.amount_uah || "").trim();
    const body = {
      kind: draft.kind,
      name: draft.name,
      phone: draft.phone,
      slot_label: draft.slot_label,
      description: draft.description,
      status: draft.status,
      amount_uah: amountRaw === "" ? null : Number.parseInt(amountRaw, 10),
    };
    const url = draft.id
      ? `${apiBase()}/api/rdn-consultation/admin/${encodeURIComponent(draft.id)}`
      : `${apiBase()}/api/rdn-consultation/admin`;
    try {
      const response = await fetch(url, {
        method: draft.id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json", token },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error("save");
      setDraft(null);
      await load();
    } catch {
      setError(t("adminSaveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row) => {
    if (!window.confirm(t("adminDeleteConfirm"))) return;
    setError("");
    try {
      const response = await fetch(
        `${apiBase()}/api/rdn-consultation/admin/${encodeURIComponent(row.id)}`,
        { method: "DELETE", headers: { token } },
      );
      if (!response.ok && response.status !== 204) throw new Error("delete");
      if (draft?.id === row.id) setDraft(null);
      await load();
    } catch {
      setError(t("adminDeleteFailed"));
    }
  };

  const todayIso = kyivTodayIso();
  const thisWeekStart = mondayOnOrBefore(todayIso);
  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDaysIso(weekStart, index)),
    [weekStart],
  );
  const { bySlot, loose } = useMemo(() => {
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
  }, [items, weekDays]);
  const times = useMemo(() => {
    const extra = [];
    bySlot.forEach((_rows, key) => {
      const time = key.split("|")[1];
      if (time && !WINDOWS.includes(time)) extra.push(time);
    });
    return [...WINDOWS, ...extra].sort();
  }, [bySlot]);
  const weekHasBookings = bySlot.size > 0;

  return (
    <section className={styles.crud}>
      <div className={styles.crudBar}>
        <h2 className={styles.crudTitle}>{t("adminSectionRdn")}</h2>
        <div className={styles.crudActions}>
          <button type="button" className={styles.submit} onClick={() => setDraft(emptyDraft())}>
            {t("adminCreate")}
          </button>
          <button type="button" className={styles.logout} onClick={load} disabled={loading}>
            {loading ? t("adminLoading") : t("adminRefresh")}
          </button>
        </div>
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
      {draft ? (
        <form className={styles.form} onSubmit={save}>
          <label className={styles.label}>
            {t("adminFieldKind")}
            <select
              className={styles.input}
              value={draft.kind}
              onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
            >
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kindLabel(t, kind)}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.label}>
            {t("adminFieldName")}
            <input
              className={styles.input}
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldPhone")}
            <input
              className={styles.input}
              value={draft.phone}
              onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldSlot")}
            <input
              className={styles.input}
              value={draft.slot_label}
              onChange={(e) => setDraft({ ...draft, slot_label: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldAmount")}
            <input
              className={styles.input}
              inputMode="numeric"
              value={draft.amount_uah}
              onChange={(e) => setDraft({ ...draft, amount_uah: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldStatus")}
            <select
              className={styles.input}
              value={draft.status}
              onChange={(e) => setDraft({ ...draft, status: e.target.value })}
            >
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label className={`${styles.label} ${styles.span2}`}>
            {t("adminFieldDescription")}
            <textarea
              className={styles.input}
              rows={3}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </label>
          <div className={styles.formButtons}>
            <button type="submit" className={styles.submit} disabled={busy}>
              {t("adminSave")}
            </button>
            <button type="button" className={styles.logout} onClick={() => setDraft(null)}>
              {t("adminCancel")}
            </button>
          </div>
        </form>
      ) : null}
      {!loading && items.length === 0 ? <p className={styles.lead}>{t("adminEmpty")}</p> : null}
      <div className={styles.weekBar}>
        <div className={styles.weekNav}>
          <button
            type="button"
            className={styles.logout}
            onClick={() => setWeekStart((current) => addDaysIso(current, -7))}
            aria-label={t("adminWeekPrev")}
          >
            ‹
          </button>
          <h3 className={styles.weekTitle}>{weekRangeLabel(weekStart, locale)}</h3>
          <button
            type="button"
            className={styles.logout}
            onClick={() => setWeekStart((current) => addDaysIso(current, 7))}
            aria-label={t("adminWeekNext")}
          >
            ›
          </button>
          {weekStart !== thisWeekStart ? (
            <button type="button" className={styles.logout} onClick={() => setWeekStart(thisWeekStart)}>
              {t("adminThisWeek")}
            </button>
          ) : null}
        </div>
      </div>
      <div className={styles.weekScroll}>
        <div className={styles.weekGrid} role="grid" aria-label={t("adminWeekAria")}>
          <div className={styles.weekCorner} />
          {weekDays.map((iso) => {
            const weekend = new Date(`${iso}T00:00:00Z`).getUTCDay() % 6 === 0;
            const headClass = [
              styles.weekHead,
              iso === todayIso ? styles.weekHeadToday : "",
              weekend ? styles.weekHeadWeekend : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div key={iso} className={headClass} role="columnheader">
                <span className={styles.weekHeadWd}>{weekdayShort(iso, locale)}</span>
                <span className={styles.weekHeadDay}>{Number(iso.slice(8, 10))}</span>
              </div>
            );
          })}
          {times.map((time) => (
            <div key={time} className={styles.weekRow} role="row">
              <div className={styles.weekTime} role="rowheader">
                {time}
              </div>
              {weekDays.map((iso) => {
                const weekend = new Date(`${iso}T00:00:00Z`).getUTCDay() % 6 === 0;
                const cellClass = [
                  styles.weekCell,
                  iso === todayIso ? styles.weekCellToday : "",
                  weekend ? styles.weekCellWeekend : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                const rows = bySlot.get(`${iso}|${time}`) || [];
                return (
                  <div key={`${iso}|${time}`} className={cellClass} role="gridcell">
                    {rows.map((row) => (
                      <button
                        key={row.id}
                        type="button"
                        className={
                          row.kind === "payment" ? styles.weekEventPayment : styles.weekEventCallback
                        }
                        onClick={() => setDraft(draftFromRow(row))}
                      >
                        <span className={styles.weekEventName}>{row.name || "—"}</span>
                        <span className={styles.weekEventMeta}>
                          {kindLabel(t, row.kind)}
                          {row.status ? ` · ${row.status}` : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {!loading && items.length > 0 && !weekHasBookings ? (
        <p className={styles.lead}>{t("adminWeekEmpty")}</p>
      ) : null}
      {loose.length > 0 ? (
        <div className={styles.weekLoose}>
          <h3 className={styles.weekTitle}>{t("adminNoSlot")}</h3>
          <ul className={styles.weekLooseList}>
            {loose.map((row) => (
              <li key={row.id}>
                <button type="button" className={styles.linkBtn} onClick={() => setDraft(draftFromRow(row))}>
                  {row.name || "—"}
                </button>
                <span className={styles.weekEventMeta}>{row.slot_label || "—"}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>{t("adminFieldKind")}</th>
              <th>{t("adminFieldName")}</th>
              <th>{t("adminFieldPhone")}</th>
              <th>{t("adminFieldSlot")}</th>
              <th>{t("adminFieldAmount")}</th>
              <th>{t("adminFieldStatus")}</th>
              <th>{t("adminColActions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{kindLabel(t, row.kind)}</td>
                <td>{row.name || "—"}</td>
                <td>{row.phone || "—"}</td>
                <td>{row.slot_label || "—"}</td>
                <td>{row.amount_uah == null ? "—" : row.amount_uah}</td>
                <td>{row.status}</td>
                <td className={styles.rowActions}>
                  <button type="button" className={styles.linkBtn} onClick={() => setDraft(draftFromRow(row))}>
                    {t("adminEdit")}
                  </button>
                  <button type="button" className={styles.linkBtn} onClick={() => remove(row)}>
                    {t("adminDelete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
