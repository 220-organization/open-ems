import { OPEN_EMS_ROUTES } from "./openEmsRoutes";

/**
 * Home / Business toggle shared by the home and commercial charger catalogs.
 * Switching uses a normal navigation so each catalog keeps its own URL.
 */
export default function ChargerCatalogSegmentBar({ t, active }) {
  return (
    <div
      className="home-charger-seg"
      role="radiogroup"
      aria-label={t("chargerCatalogSegmentAria")}
    >
      <a
        href={OPEN_EMS_ROUTES.buyHomeCharger}
        role="radio"
        aria-checked={active === "home"}
        className={`home-charger-seg__btn${active === "home" ? " home-charger-seg__btn--active" : ""}`}
      >
        {t("chargerCatalogSegmentHome")}
      </a>
      <a
        href={OPEN_EMS_ROUTES.buyCommercialCharger}
        role="radio"
        aria-checked={active === "business"}
        className={`home-charger-seg__btn${active === "business" ? " home-charger-seg__btn--active" : ""}`}
      >
        {t("chargerCatalogSegmentBusiness")}
      </a>
    </div>
  );
}
