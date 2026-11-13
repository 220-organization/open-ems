import { useMemo, useState } from "react";
import styles from "../AdminPage.module.css";
import {
  addDaysIso,
  calendarGroupOf,
  groupEventsBySlot,
  kyivTodayIso,
  mondayOnOrBefore,
  timesFromSlots,
  weekRangeLabel,
  weekdayShort,
} from "./adminCalendarUtils";

function eventClass(stylesMap, group, kind) {
  if (group === "station") return stylesMap.weekEventStation;
  if (group === "bess") return stylesMap.weekEventBess;
  if (kind === "payment") return stylesMap.weekEventPayment;
  return stylesMap.weekEventCallback;
}

export default function AdminWeekCalendar({
  t,
  locale = "uk",
  items,
  onSelect,
  metaLabel,
}) {
  const [weekStart, setWeekStart] = useState(() => mondayOnOrBefore(kyivTodayIso()));
  const todayIso = kyivTodayIso();
  const thisWeekStart = mondayOnOrBefore(todayIso);
  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDaysIso(weekStart, index)),
    [weekStart],
  );
  const { bySlot, loose } = useMemo(() => groupEventsBySlot(items, weekDays), [items, weekDays]);
  const times = useMemo(() => timesFromSlots(bySlot), [bySlot]);
  const weekHasBookings = bySlot.size > 0;

  return (
    <>
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
        <ul className={styles.calLegend} aria-label={t("adminCalLegendAria")}>
          <li>
            <span className={`${styles.calLegendSwatch} ${styles.calLegendConsultation}`} />
            {t("adminCalLegendConsultation")}
          </li>
          <li>
            <span className={`${styles.calLegendSwatch} ${styles.calLegendStation}`} />
            {t("adminCalLegendStation")}
          </li>
          <li>
            <span className={`${styles.calLegendSwatch} ${styles.calLegendBess}`} />
            {t("adminCalLegendBess")}
          </li>
        </ul>
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
                    {rows.map((row) => {
                      const group = calendarGroupOf(row);
                      return (
                        <button
                          key={row.id}
                          type="button"
                          className={eventClass(styles, group, row.kind)}
                          onClick={() => onSelect?.(row)}
                        >
                          <span className={styles.weekEventName}>{row.name || "—"}</span>
                          <span className={styles.weekEventMeta}>
                            {metaLabel ? metaLabel(row) : row.kind}
                            {row.status ? ` · ${row.status}` : ""}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {items.length > 0 && !weekHasBookings ? (
        <p className={styles.lead}>{t("adminWeekEmpty")}</p>
      ) : null}
      {loose.length > 0 ? (
        <div className={styles.weekLoose}>
          <h3 className={styles.weekTitle}>{t("adminNoSlot")}</h3>
          <ul className={styles.weekLooseList}>
            {loose.map((row) => (
              <li key={row.id}>
                <button type="button" className={styles.linkBtn} onClick={() => onSelect?.(row)}>
                  {row.name || "—"}
                </button>
                <span className={styles.weekEventMeta}>{row.slot_label || "—"}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}
