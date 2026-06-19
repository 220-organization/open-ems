"""Deye device/latest power metric parsing (grid total vs per-phase, load priority)."""

from app.deye_api import (
    _finalize_live_metrics_for_sn,
    _grid_power_signed_watts_from_data_list,
    _load_power_watts_from_data_list,
    _metric_key,
    _pv_power_watts_from_data_list,
)


def _row(key: str, value: float, unit: str = "W") -> dict:
    return {"key": key, "value": value, "unit": unit}


def test_metric_key_splits_camel_case():
    assert _metric_key("TotalGridPower") == "TOTAL_GRID_POWER"
    assert _metric_key("GridPowerL1") == "GRID_POWER_L1"
    assert _metric_key("UPSLoadPower") == "UPS_LOAD_POWER"


def test_grid_prefers_total_over_single_phase():
    dl = [
        _row("GridPowerL1", 10886.0),
        _row("GridPowerL2", 10894.0),
        _row("GridPowerL3", 10907.0),
        _row("TotalGridPower", 32687.0),
    ]
    assert _grid_power_signed_watts_from_data_list(dl) == 32687.0


def test_grid_sums_phases_when_no_total():
    dl = [
        _row("GridPowerL1", 1000.0),
        _row("GridPowerL2", 2000.0),
        _row("GridPowerL3", 3000.0),
    ]
    assert _grid_power_signed_watts_from_data_list(dl) == 6000.0


def test_load_prefers_ups_over_phase_registers():
    dl = [
        _row("LoadPowerL1", 5000.0),
        _row("LoadPowerL2", 6000.0),
        _row("UPSLoadPower", 21530.0),
        _row("TotalConsumptionPower", 22000.0),
    ]
    assert _load_power_watts_from_data_list(dl) == 21530.0


def test_finalize_derives_grid_when_load_exceeds_reported_supply():
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2601051092",
        140.0,
        13660.0,
        0.0,
        4610.0,
        50.0,
    )
    assert load_w == 13660.0
    assert grid_w == 13660.0 - 140.0
    assert bat == 140.0
    assert pv_w == 0.0


def test_finalize_derives_grid_from_load_when_imbalanced():
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2601051092",
        -130.0,
        21530.0,
        0.0,
        4610.0,
        50.0,
    )
    assert load_w == 21530.0
    assert grid_w == 21530.0 - (-130.0)
    assert bat == -130.0
    assert pv_w == 0.0


def test_pv_prefers_total_solar_power_over_mppt_rated():
    """Commercial MPPT: MPPTRatedPower is nameplate; TotalSolarPower is live PV."""
    dl = [
        _row("MPPTRatedPower", 150000.0),
        _row("RatedPower", 125000.0),
        _row("TotalSolarPower", 6140.0),
        _row("DCInputPower1", 810.0),
        _row("DCInputPower2", 1153.0),
    ]
    assert _pv_power_watts_from_data_list(dl) == 6140.0


def test_pv_cluster_rated_sum_not_used():
    """Four cluster inverters × 150 kW rated must not read as 600 kW plant PV."""
    dl = [
        _row("MPPTRatedPower", 150000.0),
        _row("TotalSolarPower", 5800.0),
    ]
    assert _pv_power_watts_from_data_list(dl) == 5800.0


def test_pv_sums_dc_inputs_when_no_total():
    dl = [
        _row("MPPTRatedPower", 150000.0),
        _row("DCInputPower1", 100.0),
        _row("DCInputPower2", 200.0),
        _row("DCInputPower3", 300.0),
    ]
    assert _pv_power_watts_from_data_list(dl) == 600.0


def test_pv_prefers_ppv_over_split_channels():
    dl = [
        _row("PPV", 4200.0),
        _row("PPV1", 2100.0),
        _row("PPV2", 2100.0),
    ]
    assert _pv_power_watts_from_data_list(dl) == 4200.0


def test_load_prefers_total_load_active_over_parallel_plant_total():
    """Parallel cluster: per-unit TotalLoadActivePower, not ParallelConnectedTotalLoadOutputPower."""
    dl = [
        _row("ParallelConnectedTotalLoadOutputPower", 116430.0),
        _row("TotalLoadActivePower", 30010.0),
        _row("LoadPhaseAActivePower", 9950.0),
        _row("LoadPhaseBActivePower", 9700.0),
        _row("LoadPhaseCActivePower", 10360.0),
    ]
    assert _load_power_watts_from_data_list(dl) == 30010.0


def test_finalize_keeps_grid_when_load_matches_supply():
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2509280353",
        25937.0,
        30010.0,
        4570.0,
        -110.0,
        50.0,
    )
    assert load_w == 30010.0
    assert grid_w == -110.0
    assert bat == 25937.0
    assert pv_w == 4570.0


def test_pv_parses_total_dc_input_for_smart_load_hybrid():
    """Smart-load hybrid: TotalDCInputPower / DCPowerPV* when PPV is absent."""
    dl = [
        _row("TotalDCInputPower", 2964.0),
        _row("DCPowerPV1", 996.0),
        _row("DCPowerPV2", 1968.0),
        _row("TotalGridPower", 0.0),
    ]
    assert _pv_power_watts_from_data_list(dl) == 2964.0


def test_smart_load_grid_stays_zero_when_pv_present():
    """2512291445-class: do not invent grid import when PV covers battery charging."""
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2512291445",
        -1102.0,
        1803.0,
        2964.0,
        0.0,
        50.0,
    )
    assert pv_w == 2964.0
    assert grid_w == 0.0
    assert bat == -1102.0
    assert load_w == 1803.0


def test_flow_balance_skips_derived_grid_when_pv_missing():
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2407316052",
        -1102.0,
        1803.0,
        0.0,
        0.0,
        50.0,
    )
    assert grid_w == 0.0
