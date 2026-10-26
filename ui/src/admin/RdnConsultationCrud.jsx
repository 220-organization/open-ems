import { useCallback, useEffect, useState } from "react";
import styles from "../AdminPage.module.css";

const KINDS = ["payment", "callback"];
const STATUSES = ["created", "SUCCESS", "FAILURE", "requested", "EXPIRED", "REVERSED"];

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

export default function RdnConsultationCrud({ t, token }) {
  const [items, setItems] = useState([]);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

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
