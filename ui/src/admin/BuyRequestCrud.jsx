import { useCallback, useEffect, useState } from "react";
import styles from "../AdminPage.module.css";
import AdminWeekCalendar from "./AdminWeekCalendar";

const KINDS = ["station", "bess", "bess_discount"];
const STATUSES = ["requested", "created", "SUCCESS", "FAILURE"];

function apiBase() {
  return (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
}

function emptyDraft() {
  return {
    id: null,
    kind: "station",
    name: "",
    phone: "",
    slot_label: "",
    title: "",
    amount_label: "",
    status: "requested",
    page_url: "",
  };
}

function draftFromRow(row) {
  return {
    id: row.id,
    kind: row.kind || "station",
    name: row.name || "",
    phone: row.phone || "",
    slot_label: row.slot_label || "",
    title: row.title || "",
    amount_label: row.amount_label || "",
    status: row.status || "requested",
    page_url: row.page_url || "",
  };
}

function kindLabel(t, kind) {
  if (kind === "bess") return t("adminBuyKindBess");
  if (kind === "bess_discount") return t("adminBuyKindBessDiscount");
  return t("adminBuyKindStation");
}

function formatRequestDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type) => parts.find((p) => p.type === type)?.value || "";
  return `${get("day")}.${get("month")}.${get("year")} ${get("hour")}:${get("minute")}`;
}

export default function BuyRequestCrud({
  t,
  token,
  locale = "uk",
  hideCalendar = false,
  onDataChanged,
}) {
  const [items, setItems] = useState([]);
  const [consultItems, setConsultItems] = useState([]);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const fetches = [
        fetch(`${apiBase()}/api/sales-buy-request/admin`, {
          headers: { token },
          cache: "no-store",
        }),
      ];
      if (!hideCalendar) {
        fetches.push(
          fetch(`${apiBase()}/api/rdn-consultation/admin`, {
            headers: { token },
            cache: "no-store",
          }),
        );
      }
      const [buyRes, rdnRes] = await Promise.all(fetches);
      if (!buyRes.ok) throw new Error("load");
      const buyData = await buyRes.json();
      setItems(Array.isArray(buyData.items) ? buyData.items : []);
      if (!hideCalendar && rdnRes?.ok) {
        const rdnData = await rdnRes.json();
        setConsultItems(
          (Array.isArray(rdnData.items) ? rdnData.items : []).map((row) => ({
            ...row,
            calendar_group: "consultation",
            source: "consultation",
          })),
        );
      } else {
        setConsultItems([]);
      }
    } catch {
      setError(t("adminLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, token, hideCalendar]);

  useEffect(() => {
    load();
  }, [load]);

  const calendarItems = [
    ...consultItems,
    ...items.map((row) => ({ ...row, source: "buy" })),
  ];

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body = {
      kind: draft.kind,
      name: draft.name,
      phone: draft.phone,
      slot_label: draft.slot_label,
      title: draft.title,
      amount_label: draft.amount_label,
      status: draft.status,
      page_url: draft.page_url,
    };
    const url = draft.id
      ? `${apiBase()}/api/sales-buy-request/admin/${encodeURIComponent(draft.id)}`
      : `${apiBase()}/api/sales-buy-request/admin`;
    try {
      const response = await fetch(url, {
        method: draft.id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json", token },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error("save");
      setDraft(null);
      await load();
      onDataChanged?.();
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
        `${apiBase()}/api/sales-buy-request/admin/${encodeURIComponent(row.id)}`,
        { method: "DELETE", headers: { token } },
      );
      if (!response.ok && response.status !== 204) throw new Error("delete");
      if (draft?.id === row.id) setDraft(null);
      await load();
      onDataChanged?.();
    } catch {
      setError(t("adminDeleteFailed"));
    }
  };

  const onSelect = (row) => {
    if (row.source === "consultation") return;
    setDraft(draftFromRow(row));
  };

  return (
    <section className={styles.crud}>
      <div className={styles.crudBar}>
        <h2 className={styles.crudTitle}>{t("adminSectionBuyRequest")}</h2>
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
              placeholder="11.11.2026, 14:00"
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldTitle")}
            <input
              className={styles.input}
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldAmountLabel")}
            <input
              className={styles.input}
              value={draft.amount_label}
              onChange={(e) => setDraft({ ...draft, amount_label: e.target.value })}
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
            {t("adminFieldPageUrl")}
            <input
              className={styles.input}
              value={draft.page_url}
              onChange={(e) => setDraft({ ...draft, page_url: e.target.value })}
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

      {!hideCalendar ? (
        <AdminWeekCalendar
          t={t}
          locale={locale}
          items={calendarItems}
          onSelect={onSelect}
          metaLabel={(row) => {
            if (row.source === "consultation") {
              return row.kind === "callback" ? t("rdnAdminKindCallback") : t("rdnAdminKindPayment");
            }
            return kindLabel(t, row.kind);
          }}
        />
      ) : null}

      {!loading && items.length === 0 ? <p className={styles.lead}>{t("adminEmpty")}</p> : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>{t("adminFieldRequestDate")}</th>
              <th>{t("adminFieldKind")}</th>
              <th>{t("adminFieldName")}</th>
              <th>{t("adminFieldPhone")}</th>
              <th>{t("adminFieldSlot")}</th>
              <th>{t("adminFieldTitle")}</th>
              <th>{t("adminFieldAmountLabel")}</th>
              <th>{t("adminFieldStatus")}</th>
              <th>{t("adminColActions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{formatRequestDate(row.created_on)}</td>
                <td>{kindLabel(t, row.kind)}</td>
                <td>{row.name || "—"}</td>
                <td>{row.phone || "—"}</td>
                <td>{row.slot_label || "—"}</td>
                <td>{row.title || "—"}</td>
                <td>{row.amount_label || "—"}</td>
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
