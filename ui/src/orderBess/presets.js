/**
 * Order BESS presets + custom BOM builder.
 * HV rule: Deye string voltage must stay ≤ 800 V → 10–15 modules (51.2 V each, max 768 V).
 */

export const MODULE_V = 51.2;
export const HV_MODULES_MIN = 10; // 512 V
export const HV_MODULES_MAX = 15; // 768 V (16 modules = 819.2 V, above 800 V cap)
export const HV_VOLTAGE_MAX = 800;
export const LV_MAX_PARALLEL = 8;
export const HV_MAX_STRINGS = 3;

export const BATTERY_MODELS = {
  // Biom LV
  "BALFP-512100-V1": {
    kwh: 5.12,
    voltage: "lv",
    brand: "biom",
    label: "Biom BALFP-512100-V1 (5,12 кВт·год)",
  },
  "BALFP-512200-V1": {
    kwh: 10.24,
    voltage: "lv",
    brand: "biom",
    label: "Biom BALFP-512200-V1 (10,24 кВт·год)",
  },
  "BALFP-512314-V2": {
    kwh: 16.08,
    voltage: "lv",
    brand: "biom",
    label: "Biom BALFP-512314-V2 (16,08 кВт·год)",
  },
  // Deye LV
  "SE-G5.1-PRO-B": {
    kwh: 5.12,
    voltage: "lv",
    brand: "deye",
    label: "Deye SE-G5.1-PRO-B (5,12 кВт·год)",
  },
  "SE-F5-PRO-C": {
    kwh: 5.12,
    voltage: "lv",
    brand: "deye",
    label: "Deye SE-F5-PRO-C (5,12 кВт·год)",
  },
  "SE-F12-C": {
    kwh: 12.28,
    voltage: "lv",
    brand: "deye",
    label: "Deye SE-F12-C (12,28 кВт·год)",
  },
  "SE-F12-MAX": {
    kwh: 12.28,
    voltage: "lv",
    brand: "deye",
    label: "Deye SE-F12-MAX (12,28 кВт·год, підігрів)",
  },
  "SE-F16-C": {
    kwh: 16.08,
    voltage: "lv",
    brand: "deye",
    label: "Deye SE-F16-C (16,08 кВт·год)",
  },
  "SE-F16-MAX": {
    kwh: 16.08,
    voltage: "lv",
    brand: "deye",
    label: "Deye SE-F16-MAX (16,08 кВт·год, підігрів)",
  },
  "BOS-G-Pack5.1": {
    kwh: 5.12,
    voltage: "hv1",
    brand: "deye",
    accessory: "bos-g",
    // ETU sheet: BOS-G-PACK5.1 PRO — HV module (string still 10–15 for ≤768 V)
    label: "Deye BOS-G-Pack5.1 PRO (5,12 кВт·год, HV)",
  },
  // Biom HV
  "BAHV-100512-LFP": {
    kwh: 5.12,
    voltage: "hv1",
    brand: "biom",
    label: "Biom BAHV-100512-LFP (5,12 кВт·год, HV-1)",
  },
  "BAHV-314512-LFP": {
    kwh: 16.08,
    voltage: "hv3",
    brand: "biom",
    label: "Biom BAHV-314512-LFP (16,08 кВт·год, HV-3)",
  },
  // Deye HV (same 10–15 modules/string rule as Biom HV, ≤ 768 V)
  "HV BOS-B-Pack16-A3-Pro": {
    kwh: 16.08,
    voltage: "hv3",
    brand: "deye",
    accessory: "bos-b",
    label: "Deye HV BOS-B-Pack16-A3-Pro (16,08 кВт·год)",
  },
};

/** Inverter options for custom builder (article → meta). LP1 = 1-phase, LP3/HP3 = 3-phase. */
export const INVERTERS = {
  "SUN-5K-SG05LP1-EU-AM2-P": { kw: 5, voltage: "lv", phase: "sp" },
  "SUN-6K-SG05LP1-EU": { kw: 6, voltage: "lv", phase: "sp" },
  "SUN-6K-SG05LP1-EU-AM2-P": { kw: 6, voltage: "lv", phase: "sp" },
  "SUN-6K-SG06LP1-EU-BM2": { kw: 6, voltage: "lv", phase: "sp" },
  "SUN-8K-SG05LP1-EU": { kw: 8, voltage: "lv", phase: "sp" },
  "SUN-8K-SG06LP1-EU-BM3": { kw: 8, voltage: "lv", phase: "sp" },
  "SUN-10K-SG02LP1-EU-AM3": { kw: 10, voltage: "lv", phase: "sp" },
  "SUN-10K-SG06LP1-EU-BM3": { kw: 10, voltage: "lv", phase: "sp" },
  "SUN-12K-SG06LP1-EU-BM3": { kw: 12, voltage: "lv", phase: "sp" },
  "SUN-12K-SG02LP1-EU": { kw: 12, voltage: "lv", phase: "sp" },
  "SUN-12K-SG05LP3-EU": { kw: 12, voltage: "lv", phase: "tp" },
  "SUN-15K-SG05LP3-EU": { kw: 15, voltage: "lv", phase: "tp" },
  "SUN-16K-SG02LP1-EU-AM3": { kw: 16, voltage: "lv", phase: "sp" },
  "SUN-20K-SG05LP3-EU": { kw: 20, voltage: "lv", phase: "tp" },
  "SUN-20K-SG01HP3-EU-AM2": { kw: 20, voltage: "hv", phase: "tp" },
  "SUN-25K-SG01HP3-EU-AM2": { kw: 25, voltage: "hv", phase: "tp" },
  "SUN-30K-SG02HP3-EU-AM3": { kw: 30, voltage: "hv", phase: "tp" },
  "SUN-50K-SG01HP3-EU-BM4": { kw: 50, voltage: "hv", phase: "tp" },
  "SUN-80K-SG02HP3-EU-EM6": { kw: 80, voltage: "hv", phase: "tp" },
  "SUN-125K-SG02HP3-EU-EM10": { kw: 125, voltage: "hv", phase: "tp" },
};

export function stringVoltage(modulesPerString) {
  return Math.round(modulesPerString * MODULE_V * 10) / 10;
}

export function isValidHvString(modulesPerString) {
  if (modulesPerString < HV_MODULES_MIN || modulesPerString > HV_MODULES_MAX)
    return false;
  return stringVoltage(modulesPerString) <= HV_VOLTAGE_MAX;
}

function line(article, qty, note) {
  return { article, qty, note: note || "" };
}

function platformsForHv1(moduleCount) {
  // MB-HV-1 holds 12 modules
  return Math.max(1, Math.ceil(moduleCount / 12));
}

function platformsForHv3(moduleCount) {
  // MB-HV-3 holds 6 modules
  return Math.max(1, Math.ceil(moduleCount / 6));
}

/**
 * Build HV accessories for N modules across `strings` strings.
 * accessory: 'bos-b' → Deye BOS-B PDU; otherwise Biom CB/platforms.
 */
function hvAccessories(series, moduleCount, strings, accessory) {
  const lines = [];
  if (accessory === "bos-g") {
    const racks = Math.max(1, Math.ceil(moduleCount / 12));
    lines.push(line("BOS-G-PDU-2", strings, `${strings}× BOS-G PDU`));
    lines.push(line("3U-HRACK (BOS G PRO)", racks, "rack 12+1"));
    return lines;
  }
  if (accessory === "bos-b") {
    lines.push(line("BOS-B-PDU-2-A-Pro", strings, `${strings}× BOS-B PDU`));
    return lines;
  }
  if (series === "hv1") {
    lines.push(line("CB-HV-100", strings, `${strings}× control box`));
    lines.push(line("MB-HV-1", platformsForHv1(moduleCount), "platform(s)"));
  } else {
    lines.push(line("CB-HV-160", strings, `${strings}× control box`));
    lines.push(line("MB-HV-3", platformsForHv3(moduleCount), "platform(s)"));
    lines.push(line("PC-HV-3-3.2m", Math.max(1, strings), "HV-3 cable"));
  }
  return lines;
}

/** LV accessories (e.g. Deye BOS-G PDU). */
function lvAccessories(accessory) {
  if (accessory === "bos-g") {
    return [line("BOS-G-PDU-2", 1, "BOS-G PDU")];
  }
  return [];
}

/**
 * Allowed kWh options for a battery model + voltage class.
 * @returns {{ kwh: number, modules: number, strings?: number, modulesPerString?: number }[]}
 */
export function allowedKwhOptions(batteryArticle, voltageClass) {
  const bat = BATTERY_MODELS[batteryArticle];
  if (!bat) return [];
  const out = [];
  if (voltageClass === "lv") {
    for (let q = 1; q <= LV_MAX_PARALLEL; q += 1) {
      out.push({ kwh: Math.round(bat.kwh * q * 100) / 100, modules: q });
    }
    return out;
  }
  // HV: strings of 10–15 modules (≤ 768 V), 1…HV_MAX_STRINGS strings
  for (let strings = 1; strings <= HV_MAX_STRINGS; strings += 1) {
    for (let mps = HV_MODULES_MIN; mps <= HV_MODULES_MAX; mps += 1) {
      const voltageV = stringVoltage(mps);
      if (voltageV > HV_VOLTAGE_MAX) continue;
      const modules = strings * mps;
      out.push({
        kwh: Math.round(bat.kwh * modules * 100) / 100,
        modules,
        strings,
        modulesPerString: mps,
        voltageV,
      });
    }
  }
  // Unique by kwh ascending
  const seen = new Set();
  return out
    .sort((a, b) => a.kwh - b.kwh)
    .filter((o) => {
      const k = o.kwh.toFixed(2);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
}

export function kwhRangeLabel(options) {
  if (!options.length) return "—";
  const min = options[0].kwh;
  const max = options[options.length - 1].kwh;
  return `${min} … ${max} кВт·год`;
}

/**
 * Build BOM for custom selection.
 * @returns {{ lines: {article, qty, note}[], kwh: number, kw: number, voltageClass: string, meta: object }}
 */
export function buildCustomBom(inverterArticle, batteryArticle, targetKwh) {
  const inv = INVERTERS[inverterArticle];
  const bat = BATTERY_MODELS[batteryArticle];
  if (!inv || !bat) {
    return {
      lines: [],
      kwh: 0,
      kw: 0,
      voltageClass: "",
      meta: { error: "unknown SKU" },
    };
  }

  if (inv.voltage === "lv") {
    if (bat.voltage !== "lv") {
      return {
        lines: [],
        kwh: 0,
        kw: inv.kw,
        voltageClass: "lv",
        meta: { error: "LV inverter needs LV battery" },
      };
    }
    const opts = allowedKwhOptions(batteryArticle, "lv");
    const match =
      opts.find((o) => Math.abs(o.kwh - targetKwh) < 0.01) ||
      opts.reduce(
        (best, o) =>
          !best || Math.abs(o.kwh - targetKwh) < Math.abs(best.kwh - targetKwh)
            ? o
            : best,
        null,
      );
    if (!match) {
      return {
        lines: [],
        kwh: 0,
        kw: inv.kw,
        voltageClass: "lv",
        meta: { error: "no kWh match" },
      };
    }
    return {
      lines: [
        line(inverterArticle, 1),
        line(batteryArticle, match.modules),
        ...lvAccessories(bat.accessory),
      ],
      kwh: match.kwh,
      kw: inv.kw,
      voltageClass: "lv",
      meta: { modules: match.modules },
    };
  }

  // HV
  if (bat.voltage !== "hv1" && bat.voltage !== "hv3") {
    return {
      lines: [],
      kwh: 0,
      kw: inv.kw,
      voltageClass: "hv",
      meta: { error: "HV inverter needs HV battery" },
    };
  }
  const opts = allowedKwhOptions(batteryArticle, "hv");
  const match =
    opts.find((o) => Math.abs(o.kwh - targetKwh) < 0.01) ||
    opts.reduce(
      (best, o) =>
        !best || Math.abs(o.kwh - targetKwh) < Math.abs(best.kwh - targetKwh)
          ? o
          : best,
      null,
    );
  if (!match || !isValidHvString(match.modulesPerString)) {
    return {
      lines: [],
      kwh: 0,
      kw: inv.kw,
      voltageClass: "hv",
      meta: { error: "invalid HV string" },
    };
  }
  const series = bat.voltage;
  const invQty = inv.kw >= 200 ? Math.ceil(inv.kw / 80) : 1;
  // For multi-inverter presets like 240 kW we pass synthetic inverter; custom uses single SKU qty 1
  const lines = [
    line(inverterArticle, 1),
    line(
      batteryArticle,
      match.modules,
      `${match.strings}×${match.modulesPerString} @ ${match.voltageV} V`,
    ),
    ...hvAccessories(series, match.modules, match.strings, bat.accessory),
  ];
  return {
    lines,
    kwh: match.kwh,
    kw: inv.kw,
    voltageClass: "hv",
    meta: {
      strings: match.strings,
      modulesPerString: match.modulesPerString,
      voltageV: match.voltageV,
      invQty,
    },
  };
}

/** Home segment: LV kits and anything under this capacity (kWh). */
export const HOME_KWH_MAX = 40;

/** 'home' | 'biz' for the simplified preset chips. */
export function presetSegment(p) {
  if (!p) return "biz";
  if (p.group === "lv" || Number(p.kwh) < HOME_KWH_MAX) return "home";
  return "biz";
}

/** Brand label shown on a preset chip. */
export function presetBrand(p) {
  if (!p) return "Deye";
  const g = String(p.group || "");
  if (g.startsWith("sigen")) return "Sigenergy";
  if (g === "cabinet") return "Ubetter";
  return "Deye";
}

/** Fixed presets from the plan. */
export const PRESETS = [
  {
    id: "lv-6-16",
    group: "lv",
    label: "6 кВт + 16 кВт·год",
    kw: 6,
    kwh: 16.08,
    lines: [line("SUN-6K-SG06LP1-EU-BM2", 1), line("BALFP-512314-V2", 1)],
  },
  {
    id: "lv-6-5",
    group: "lv",
    label: "6 кВт + 5 кВт·год",
    kw: 6,
    kwh: 5.12,
    lines: [line("SUN-6K-SG06LP1-EU-BM2", 1), line("BALFP-512100-V1", 1)],
  },
  {
    id: "lv-6-10",
    group: "lv",
    label: "6 кВт + 10 кВт·год",
    kw: 6,
    kwh: 10.24,
    lines: [line("SUN-6K-SG06LP1-EU-BM2", 1), line("BALFP-512200-V1", 1)],
  },
  {
    id: "lv-10-16",
    group: "lv",
    label: "10 кВт + 16 кВт·год",
    kw: 10,
    kwh: 16.08,
    lines: [line("SUN-10K-SG06LP1-EU-BM3", 1), line("BALFP-512314-V2", 1)],
  },
  {
    id: "lv-10-20",
    group: "lv",
    label: "10 кВт + 20 кВт·год",
    kw: 10,
    kwh: 20.48,
    lines: [line("SUN-10K-SG06LP1-EU-BM3", 1), line("BALFP-512200-V1", 2)],
  },
  {
    id: "lv-12-32",
    group: "lv",
    label: "12 кВт + 32 кВт·год",
    kw: 12,
    kwh: 32.16,
    lines: [line("SUN-12K-SG05LP3-EU", 1), line("BALFP-512314-V2", 2)],
  },
  {
    id: "hv-50-60",
    group: "hv",
    label: "50 кВт + 60 кВт·год",
    kw: 50,
    kwh: 61.44,
    lines: [
      line("SUN-50K-SG01HP3-EU-BM4", 1),
      line("BAHV-100512-LFP", 12, "1×12 @ 614 V"),
      line("CB-HV-100", 1),
      line("MB-HV-1", 1),
    ],
  },
  {
    id: "hv-80-160",
    group: "hv",
    label: "80 кВт + 160 кВт·год",
    kw: 80,
    kwh: 160.8,
    lines: [
      line("SUN-80K-SG02HP3-EU-EM6", 1),
      line("BAHV-314512-LFP", 10, "1×10 @ 512 V"),
      line("CB-HV-160", 1),
      line("MB-HV-3", 2),
      line("PC-HV-3-3.2m", 1),
    ],
  },
  {
    id: "hv-240-620",
    group: "hv",
    label: "240 кВт + 620 кВт·год",
    kw: 240,
    kwh: 627.12,
    lines: [
      line("SUN-80K-SG02HP3-EU-EM6", 3, "3×80 кВт"),
      line("BAHV-314512-LFP", 39, "3×13 @ 666 V"),
      line("CB-HV-160", 3),
      line("MB-HV-3", 7),
      line("PC-HV-3-3.2m", 3),
    ],
  },
  {
    id: "ubetter-125-241",
    group: "cabinet",
    label: "125 кВт + 241 кВт·год",
    kw: 125,
    kwh: 241,
    lines: [line("UBT-241KNFBN S125-A120P4", 1, "1× Ubetter cabinet")],
  },
];

/**
 * Sigenergy kits from the Nov 2026 price list and datasheets.
 * stor EC already includes the battery controller (1–6 SigenStor BAT).
 * hybrid inverters do not: add one SigenStor BC plus 1–6 SigenStor BAT.
 * neo EC includes backup, so the kit is Neo EC + 1–6 Neo BAT + Neo ground kit.
 * C&I HYB connects 4–21 SigenStack BAT 12.06 modules (datasheet).
 * The datasheet allows a taller column, but a quote caps each rack at 7×12 kWh.
 * Six modules per rack is the recommendation. Seven is acceptable. Eight
 * modules plus the controller is about 2.5 m and is at the installer's risk,
 * so the BOM splits that column onto another SUB base. The controller tops
 * the main tower; each extra tower gets a SUB base and a cover. Use 0.5C
 * hardware when kW/kWh ≤ 0.5 (the 125 kW + 252 kWh invoice), otherwise 1C.
 */
export const SIGEN_HOME_MODULES_MIN = 1;
export const SIGEN_HOME_MODULES_MAX = 6;
export const SIGEN_BIZ_MODULES_MIN = 4;
export const SIGEN_BIZ_MODULES_MAX = 21;
/** Preferred module count on one SigenStack rack. */
export const SIGEN_BIZ_MODULES_RECOMMENDED = 6;
/**
 * Hard cap per rack in a quote: 7×12 kWh.
 * Eight modules plus the controller is about 2.5 m and is not quoted.
 */
export const SIGEN_BIZ_MODULES_PER_BASE = 7;

export const SIGEN_GROUND_KIT = "SigenStor Installation Kit for Ground";
export const SIGEN_NEO_GROUND_KIT = "SigenStor Neo Installation Kit Ground";
export const SIGEN_BC = "SigenStor BC";
export const SIGEN_STACK_BC_05 = "SigenStack BC M2-0.5C-BST";
export const SIGEN_STACK_BC_1 = "SigenStack BC M2-1C-BST";
export const SIGEN_STACK_MAIN_05 = "SigenStack Base MAIN-0.5C";
export const SIGEN_STACK_MAIN_1 = "SigenStack Base MAIN-1C";
export const SIGEN_STACK_SUB_05 = "SigenStack Base SUB-0.5C";
export const SIGEN_STACK_SUB_1 = "SigenStack Base SUB-1C";
export const SIGEN_STACK_COVER = "SigenStack Cover";
export const SIGEN_STACK_CABLES = "SigenStack BC Cables 4m";
export const SIGEN_COMM_MODULE = "Sigen Communication Module";

export function sigenGatewayArticle(phase) {
  return phase === "sp"
    ? "Sigen Gateway Home SP 12K"
    : "Sigen Gateway Home TP 30K";
}

export function sigenStackSubBases(modules) {
  return Math.max(0, Math.ceil(modules / SIGEN_BIZ_MODULES_PER_BASE) - 1);
}

/** 0.5C controller and bases when inverter power stays within half the stack energy. */
export function sigenStackUsesHalfC(kw, kwh) {
  if (!kwh || kwh <= 0) return false;
  return kw / kwh <= 0.5 + 1e-6;
}

/** Battery family that pairs with an inverter: stor (also hybrid), neo, or stack. */
export function sigenCompatibleBatteryFamily(invArticle) {
  const inv = SIGEN_INVERTERS[invArticle];
  if (!inv) return "stor";
  if (inv.family === "neo" || inv.family === "stack") return inv.family;
  return "stor";
}

export const SIGEN_INVERTERS = {
  "SigenStor EC 3.0 SP": { kw: 3, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 4.0 SP": { kw: 4, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 5.0 SP": { kw: 5, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 6.0 SP": { kw: 6, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 8.0 SP": { kw: 8, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 10.0 SP": { kw: 10, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 12.0 SP": { kw: 12, line: "home", family: "stor", phase: "sp" },
  "SigenStor EC 5.0 TP": { kw: 5, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 6.0 TP": { kw: 6, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 8.0 TP": { kw: 8, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 10.0 TP": { kw: 10, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 12.0 TP": { kw: 12, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 15.0 TP": { kw: 15, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 17.0 TP": { kw: 17, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 20.0 TP": { kw: 20, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 25.0 TP": { kw: 25, line: "home", family: "stor", phase: "tp" },
  "SigenStor EC 30.0 TP": { kw: 30, line: "home", family: "stor", phase: "tp" },
  "Sigen Hybrid 5.0 SP2": { kw: 5, line: "home", family: "hybrid", phase: "sp" },
  "Sigen Hybrid 6.0 SP2": { kw: 6, line: "home", family: "hybrid", phase: "sp" },
  "Sigen Hybrid 8.0 TP2": { kw: 8, line: "home", family: "hybrid", phase: "tp" },
  "Sigen Hybrid 10.0 TP2": { kw: 10, line: "home", family: "hybrid", phase: "tp" },
  "Sigen Hybrid 12.0 TP2": { kw: 12, line: "home", family: "hybrid", phase: "tp" },
  "SigenStor Neo EC 3.0 SP": { kw: 3, line: "home", family: "neo", phase: "sp" },
  "SigenStor Neo EC 5.0 SP": { kw: 5, line: "home", family: "neo", phase: "sp" },
  "SigenStor Neo EC 6.0 SP": { kw: 6, line: "home", family: "neo", phase: "sp" },
  "SigenStor Neo EC 8.0 SP": { kw: 8, line: "home", family: "neo", phase: "sp" },
  "SigenStor Neo EC 10.0 SP": { kw: 10, line: "home", family: "neo", phase: "sp" },
  "SigenStor Neo EC 12.0 SP": { kw: 12, line: "home", family: "neo", phase: "sp" },
  "SigenStor Neo EC 6.0 TP": { kw: 6, line: "home", family: "neo", phase: "tp" },
  "SigenStor Neo EC 8.0 TP": { kw: 8, line: "home", family: "neo", phase: "tp" },
  "SigenStor Neo EC 10.0 TP": { kw: 10, line: "home", family: "neo", phase: "tp" },
  "SigenStor Neo EC 12.0 TP": { kw: 12, line: "home", family: "neo", phase: "tp" },
  "SigenStor Neo EC 15.0 TP": { kw: 15, line: "home", family: "neo", phase: "tp" },
  "Sigen PV 50M1-HYB": { kw: 50, line: "biz", family: "stack", phase: "tp" },
  "Sigen PV 60M1-HYB": { kw: 60, line: "biz", family: "stack", phase: "tp" },
  "Sigen PV 80M1-HYB": { kw: 80, line: "biz", family: "stack", phase: "tp" },
  "Sigen PV 100M1-HYB": { kw: 100, line: "biz", family: "stack", phase: "tp" },
  "Sigen PV 110M1-HYB": { kw: 110, line: "biz", family: "stack", phase: "tp" },
  "Sigen PV 125M1-HYB": { kw: 125, line: "biz", family: "stack", phase: "tp" },
};

export const SIGEN_BATTERIES = {
  "SigenStor BAT 6.0": { kwh: 6, line: "home", family: "stor" },
  "SigenStor BAT 10.0": { kwh: 10, line: "home", family: "stor" },
  "SigenStor Neo BAT 6.0": { kwh: 6.02, line: "home", family: "neo" },
  "SigenStor Neo BAT 8.0": { kwh: 7.52, line: "home", family: "neo" },
  "SigenStack BAT 12.06": { kwh: 12, line: "biz", family: "stack" },
};

/**
 * Allowed kWh options for a Sigenergy inverter + battery pair.
 * @returns {{ kwh: number, modules: number }[]}
 */
export function sigenKwhOptions(invArticle, batArticle) {
  const inv = SIGEN_INVERTERS[invArticle];
  const bat = SIGEN_BATTERIES[batArticle];
  if (!inv || !bat || sigenCompatibleBatteryFamily(invArticle) !== bat.family) {
    return [];
  }
  const stack = inv.family === "stack";
  const min = stack ? SIGEN_BIZ_MODULES_MIN : SIGEN_HOME_MODULES_MIN;
  const max = stack ? SIGEN_BIZ_MODULES_MAX : SIGEN_HOME_MODULES_MAX;
  const out = [];
  for (let modules = min; modules <= max; modules += 1) {
    out.push({
      kwh: Math.round(bat.kwh * modules * 100) / 100,
      modules,
    });
  }
  return out;
}

/**
 * Build BOM for a custom Sigenergy selection.
 * @returns {{ lines: {article, qty, note}[], kwh: number, kw: number, voltageClass: string, meta: object }}
 */
export function buildSigenBom(invArticle, batArticle, targetKwh) {
  const inv = SIGEN_INVERTERS[invArticle];
  const bat = SIGEN_BATTERIES[batArticle];
  if (!inv || !bat || inv.line !== bat.line) {
    return {
      lines: [],
      kwh: 0,
      kw: inv?.kw || 0,
      voltageClass: "",
      meta: { error: "unknown SKU" },
    };
  }
  const opts = sigenKwhOptions(invArticle, batArticle);
  const match =
    opts.find((o) => Math.abs(o.kwh - targetKwh) < 0.01) ||
    opts.reduce(
      (best, o) =>
        !best || Math.abs(o.kwh - targetKwh) < Math.abs(best.kwh - targetKwh)
          ? o
          : best,
      null,
    );
  if (!match) {
    return {
      lines: [],
      kwh: 0,
      kw: inv.kw,
      voltageClass: inv.line === "home" ? "sigen-home" : "sigen-biz",
      meta: { error: "no kWh match" },
    };
  }

  const batNote =
    match.modules > 1 ? `${match.modules}×${bat.kwh} кВт·год` : "";
  const homeMeta = {
    kwh: match.kwh,
    kw: inv.kw,
    voltageClass: "sigen-home",
    meta: { modules: match.modules, line: "home", family: inv.family },
  };

  if (inv.family === "neo") {
    return {
      ...homeMeta,
      lines: [
        line(invArticle, 1),
        line(batArticle, match.modules, batNote),
        line(SIGEN_NEO_GROUND_KIT, 1),
      ],
    };
  }

  if (inv.family === "hybrid") {
    return {
      ...homeMeta,
      lines: [
        line(invArticle, 1, "без БМС"),
        line(batArticle, match.modules, batNote),
        line(SIGEN_BC, 1, "контролер батареї"),
        line(sigenGatewayArticle(inv.phase), 1),
        line(SIGEN_GROUND_KIT, 1),
      ],
    };
  }

  if (inv.family !== "stack") {
    return {
      ...homeMeta,
      lines: [
        line(invArticle, 1),
        line(batArticle, match.modules, batNote),
        line(sigenGatewayArticle(inv.phase), 1),
        line(SIGEN_GROUND_KIT, 1),
      ],
    };
  }

  const subBases = sigenStackSubBases(match.modules);
  const towers = subBases + 1;
  const halfC = sigenStackUsesHalfC(inv.kw, match.kwh);
  const stackBatNote =
    towers > 1
      ? `${match.modules}×${bat.kwh} кВт·год · ${towers} стійки, до ${SIGEN_BIZ_MODULES_PER_BASE} на стійку`
      : `${match.modules}×${bat.kwh} кВт·год`;
  const lines = [
    line(invArticle, 1, "гібрид, бекап / острів"),
    line(batArticle, match.modules, stackBatNote),
    line(
      halfC ? SIGEN_STACK_BC_05 : SIGEN_STACK_BC_1,
      1,
      halfC ? "контролер 0.5C" : "контролер 1C",
    ),
    line(halfC ? SIGEN_STACK_MAIN_05 : SIGEN_STACK_MAIN_1, 1),
  ];
  if (subBases > 0) {
    lines.push(line(halfC ? SIGEN_STACK_SUB_05 : SIGEN_STACK_SUB_1, subBases));
    lines.push(line(SIGEN_STACK_COVER, subBases));
  }
  lines.push(line(SIGEN_STACK_CABLES, 1, "комплект кабелів"));
  lines.push(line(SIGEN_COMM_MODULE, 1, "Wi‑Fi"));
  return {
    lines,
    kwh: match.kwh,
    kw: inv.kw,
    voltageClass: "sigen-biz",
    meta: {
      modules: match.modules,
      line: "biz",
      family: "stack",
      subBases,
      towers,
    },
  };
}

function sigenPreset(id, group, tier, invArticle, batArticle, kwh) {
  const bom = buildSigenBom(invArticle, batArticle, kwh);
  const kwhLabel = Number.isInteger(bom.kwh)
    ? String(bom.kwh)
    : String(bom.kwh).replace(".", ",");
  return {
    id,
    group,
    tier,
    label: `${bom.kw} кВт + ${kwhLabel} кВт·год`,
    kw: bom.kw,
    kwh: bom.kwh,
    lines: bom.lines,
    meta: bom.meta,
  };
}

/**
 * Repeat one C&I stack across several inverters.
 * Mirrors the Deye 3×80 kW plant: each inverter keeps its own 4–21 module stack.
 */
function sigenParallelPreset(
  id,
  group,
  tier,
  invArticle,
  batArticle,
  kwhEach,
  inverters,
) {
  const one = buildSigenBom(invArticle, batArticle, kwhEach);
  const lines = one.lines.map((item) => {
    let note = item.note;
    if (item.article === invArticle) note = `${inverters}×${one.kw} кВт`;
    if (item.article === batArticle && note) note = `${inverters}×${note}`;
    return line(item.article, item.qty * inverters, note);
  });
  const kwh = Math.round(one.kwh * inverters * 100) / 100;
  const kw = one.kw * inverters;
  const kwhLabel = Number.isInteger(kwh)
    ? String(kwh)
    : String(kwh).replace(".", ",");
  return {
    id,
    group,
    tier,
    label: `${kw} кВт + ${kwhLabel} кВт·год`,
    kw,
    kwh,
    lines,
    meta: one.meta,
  };
}

/** Sigenergy block: home (SigenStor) and business (SigenStack), min / avg / max. */
export const SIGENERGY_PRESETS = [
  sigenPreset(
    "sigen-home-min",
    "sigen-home",
    "min",
    "SigenStor EC 3.0 SP",
    "SigenStor BAT 6.0",
    6,
  ),
  sigenPreset(
    "sigen-home-avg",
    "sigen-home",
    "avg",
    "SigenStor EC 10.0 TP",
    "SigenStor BAT 10.0",
    20,
  ),
  sigenPreset(
    "sigen-home-max",
    "sigen-home",
    "max",
    "SigenStor EC 30.0 TP",
    "SigenStor BAT 10.0",
    60,
  ),
  sigenPreset(
    "sigen-biz-min",
    "sigen-biz",
    "min",
    "Sigen PV 50M1-HYB",
    "SigenStack BAT 12.06",
    48,
  ),
  sigenPreset(
    "sigen-biz-avg",
    "sigen-biz",
    "avg",
    "Sigen PV 80M1-HYB",
    "SigenStack BAT 12.06",
    96,
  ),
  sigenPreset(
    "sigen-125-168",
    "sigen-biz",
    "168",
    "Sigen PV 125M1-HYB",
    "SigenStack BAT 12.06",
    168,
  ),
  sigenPreset(
    "sigen-biz-max",
    "sigen-biz",
    "max",
    "Sigen PV 125M1-HYB",
    "SigenStack BAT 12.06",
    252,
  ),
  sigenParallelPreset(
    "sigen-240-612",
    "sigen-biz",
    "parallel",
    "Sigen PV 80M1-HYB",
    "SigenStack BAT 12.06",
    204,
    3,
  ),
];

export const CUSTOM_PRESET_ID = "custom";

export const BUSINESS_TYPES = [
  {
    id: "cash",
    labelKey: "orderBessBizCash",
    priceLabelKey: "orderBessPriceCash",
  },
  {
    id: "fop",
    labelKey: "orderBessBizFop",
    priceLabelKey: "orderBessPriceNoVat",
  },
  {
    id: "vat",
    labelKey: "orderBessBizVat",
    priceLabelKey: "orderBessPriceVat",
  },
];

export const DISCOUNT_UNITS = Array.from({ length: 219 }, (_, i) => i + 2); // 2 … 220

/** Map Deye battery SKU → equivalent Biom module for price comparison. */
export const DEYE_TO_BIOM_BATTERY = {
  "HV BOS-B-Pack16-A3-Pro": "BAHV-314512-LFP",
  "SE-G5.1-PRO-B": "BALFP-512100-V1",
  "SE-F5-PRO-C": "BALFP-512100-V1",
  "SE-F12-C": "BALFP-512200-V1",
  "SE-F12-MAX": "BALFP-512200-V1",
  "SE-F16-C": "BALFP-512314-V2",
  "SE-F16-MAX": "BALFP-512314-V2",
  "BOS-G-Pack5.1": "BAHV-100512-LFP",
};

/**
 * If current custom selection uses a Deye battery, return Biom alternative savings.
 * @returns {{ biomArticle: string, savingsUsd: number, deyeTotal: number, biomTotal: number } | null}
 */
export function computeBiomSavings({
  inverterArticle,
  batteryArticle,
  targetKwh,
  businessType,
  priceItems,
  findItemFn,
}) {
  const bat = BATTERY_MODELS[batteryArticle];
  if (!bat || bat.brand !== "deye") return null;
  const biomArticle = DEYE_TO_BIOM_BATTERY[batteryArticle];
  if (!biomArticle || !BATTERY_MODELS[biomArticle]) return null;

  const deyeBom = buildCustomBom(inverterArticle, batteryArticle, targetKwh);
  const biomBom = buildCustomBom(inverterArticle, biomArticle, targetKwh);
  if (!deyeBom.lines?.length || !biomBom.lines?.length) return null;

  const sumBom = (bom) => {
    let total = 0;
    for (const l of bom.lines) {
      const item = findItemFn(priceItems, l.article);
      const unit = unitPriceUsd(item, businessType);
      if (unit == null) return null;
      total += unit * l.qty;
    }
    return Math.round(total * 100) / 100;
  };

  const deyeTotal = sumBom(deyeBom);
  const biomTotal = sumBom(biomBom);
  if (deyeTotal == null || biomTotal == null) return null;

  return {
    biomArticle,
    biomLabel: BATTERY_MODELS[biomArticle].label,
    savingsUsd: Math.round((deyeTotal - biomTotal) * 100) / 100,
    deyeTotal,
    biomTotal,
  };
}

/** True when the installer sheet has no inbound/arrival dates for this SKU. */
export function hasNoArrivalDates(item) {
  if (!item) return false;
  const text = `${item.availabilityInstaller || ""} ${item.availability || ""}`;
  return /дані\s*про\s*приход|приход[иі]\s+відсутн|нет\s+данных\s+о\s+приход|no\s+arrival\s+data/i.test(
    text,
  );
}

/** Energotrendy Ukrainy (5–10 days from the Netherlands) is the displayed vendor. */
export function isEtuVendor(item) {
  if (!item) return false;
  const text = `${item.availabilityInstaller || ""} ${item.availability || ""}`;
  return /нідерланд|netherland|енерготренд|energotrend/i.test(text);
}

/** Price unit USD for one item given business type (BIOM install sheet + ETU overlay). */
export function unitPriceUsd(item, businessType) {
  if (!item) return null;

  // NL vendor: always the ETU sheet prepaid price, ignoring FOP / VAT / installer chips.
  if (isEtuVendor(item) && item.etuUsd != null) {
    return Math.round(Number(item.etuUsd) * 100) / 100;
  }

  // Cash / installer 220-km.com — cheapest among install-sheet price columns.
  if (businessType === "cash") {
    const base = item.installerCheapestUsd ?? item.installerUsd;
    return base == null ? null : Math.round(Number(base) * 100) / 100;
  }

  // FOP — install sheet «Роздріб». VAT payers — that retail price + 20%.
  if (businessType === "fop") {
    const base = item.retailUsd;
    return base == null ? null : Math.round(Number(base) * 100) / 100;
  }
  if (businessType === "vat") {
    const base = item.retailVatUsd;
    return base == null ? null : Math.round(Number(base) * 100) / 100;
  }
  return null;
}
