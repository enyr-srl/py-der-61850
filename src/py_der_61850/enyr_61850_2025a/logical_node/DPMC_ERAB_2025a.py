import logging
import math
import os
import shutil
from datetime import timedelta
from typing import Any, Callable, cast

from pyomo.core.base.var import VarData
from pyomo.environ import ConcreteModel, Constraint, Objective, RangeSet, Set, SolverFactory, Var, minimize, value
from pyomo.opt import TerminationCondition

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DMDR_2025a import ORG_DMDR_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DPMC_2025a import ORG_DPMC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_DAM_2025a import ORG_Frcs_DAM_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_GN_2025a import ORG_Frcs_GN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_LOD_2025a import ORG_Frcs_LOD_2025a
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.data_objects.VSG_2025a import VSG_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DPMC_ERAB_2025a(LNodeType):
    """The DER power management capability is basically a “black box” component that acts as the intelligence for managing DERs. Just like the other components of DERs, it can be hierarchical, with higher level power management systems managing lower level power management systems. The power management functions generally include applications that can use the input from the DER resources to assess situations and provide feedback to the DER resources in the form of modifying the settings, requests, or commands in order to meet specified “goals”. These goals could come from an upper level power management function, operational functions, and DER operator input, each associated with different priorities"""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        for i in range(1, self._visitor.get_users_length() + 1):
            setattr(self, f"ReqW{i}", MV_2025a())
            setattr(self, f"WhichLogic{i}", VSG_2025a())  # SC_EA_1BESS, CSC_SC_EA_mBESS, CSC_NotControllable
            setattr(self, f"WhichControl{i}", VSG_2025a())  # HuaweiAPI, ZucchettiModbus, Uncontrollable, Unavailable
            setattr(self, f"BessDpmcRef{i}", ORG_DPMC_2025a())

        # Settings
        self.DERRef: ORG_DMDR_2025a = ORG_DMDR_2025a()  # Reference to the DER resource LN (a child of DERResourceLN)
        self.FrcsRefDAM: ORG_Frcs_DAM_2025a = ORG_Frcs_DAM_2025a()
        self.FrcsRefLOD: ORG_Frcs_LOD_2025a = ORG_Frcs_LOD_2025a()
        self.FrcsRefGN: ORG_Frcs_GN_2025a = ORG_Frcs_GN_2025a()

        self._logger = logging.getLogger(__name__)

    @staticmethod
    def _resolve_cbc_executable() -> str:
        env_path = os.getenv("CBC_EXECUTABLE")
        if env_path:
            return env_path

        for candidate in ("cbc", "cbc.exe"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        raise RuntimeError(
            "CBC solver not found. Install CBC and add it to PATH, or set CBC_EXECUTABLE."
        )

    @staticmethod
    def _is_finite_forecast_value(value: object) -> bool:
        if value is None:
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _sanitize_forecast_samples(self, forecast: TES_2025a) -> list[int]:
        invalid_indices: list[int] = []
        for index, value in enumerate(forecast.val):
            if self._is_finite_forecast_value(value):
                continue
            forecast.val[index] = None
            invalid_indices.append(index)
            if index < len(forecast.q):
                forecast.q[index].validity = ValidityKind_2025a.invalid
            else:
                while len(forecast.q) < index:
                    forecast.q.append(Quality_2025a(0))
                forecast.q.append(Quality_2025a(1))
        return invalid_indices

    def _check_forecast_validity(self, forecast: TES_2025a, forecast_name: str, user_id: str) -> bool:
        """Check if a forecast has valid data. Returns True if usable, False if all invalid.

        Validity levels:
        - good: all values are valid
        - questionable: values are interpolated/estimated but usable
        - invalid: values are missing/invalid - cannot use
        """
        invalid_indices = self._sanitize_forecast_samples(forecast)
        if invalid_indices:
            shown_indices = invalid_indices[:10]
            suffix = "..." if len(invalid_indices) > 10 else ""
            self._logger.warning(
                f"[DPMC_ERAB] {forecast_name} for user '{user_id}' has non-finite samples at indices {shown_indices}{suffix}. Marked INVALID."
            )

        if not forecast.q:
            # No quality info, check if val contains None
            if not forecast.val or all(v is None for v in forecast.val):
                self._logger.warning(
                    f"[DPMC_ERAB] {forecast_name} for user '{user_id}' has no data (empty or all None). Skipping user."
                )
                return False
            if any(v is None for v in forecast.val):
                self._logger.warning(
                    f"[DPMC_ERAB] {forecast_name} for user '{user_id}' has missing/non-finite samples and no quality metadata. Skipping user."
                )
                return False
            return True

        invalid_count = sum(1 for q in forecast.q if q.validity == ValidityKind_2025a.invalid)
        questionable_count = sum(1 for q in forecast.q if q.validity == ValidityKind_2025a.questionable)
        total = len(forecast.q)

        if invalid_count == total:
            self._logger.warning(
                f"[DPMC_ERAB] {forecast_name} for user '{user_id}' is entirely INVALID ({invalid_count}/{total} samples). Skipping user."
            )
            return False

        if invalid_count > 0:
            self._logger.warning(
                f"[DPMC_ERAB] {forecast_name} for user '{user_id}' has {invalid_count}/{total} INVALID samples. Skipping user."
            )
            return False

        if questionable_count > 0:
            self._logger.debug(
                f"[DPMC_ERAB] {forecast_name} for user '{user_id}' has {questionable_count}/{total} QUESTIONABLE samples (interpolated/estimated)."
            )

        return True

    @staticmethod
    def _solver_result_has_solution(results: Any) -> bool:
        solutions = getattr(results, "solution", None)
        if solutions is None:
            return False
        try:
            return len(solutions) > 0
        except TypeError:
            return bool(solutions)

    @staticmethod
    def _summarize_indices(indices: list[int], limit: int = 5) -> str:
        shown_indices = indices[:limit]
        suffix = "..." if len(indices) > limit else ""
        return f"{shown_indices}{suffix}"

    @staticmethod
    def _resolved_series_sample_rate(series: TES_2025a) -> timedelta:
        return series.smpRate or timedelta(minutes=15)

    @classmethod
    def _resolved_series_sample_rate_hours(cls, series: TES_2025a) -> float:
        return cls._resolved_series_sample_rate(series).total_seconds() / 3600

    @classmethod
    def _clone_series_with_values(cls, source: TES_2025a, values: list[Any]) -> TES_2025a:
        cloned = TES_2025a()
        cloned.t = source.t
        cloned.smpRate = cls._resolved_series_sample_rate(source)
        cloned.smpNum = source.smpNum or len(values)
        cloned.val = values
        cloned.q = list(source.q)
        return cloned

    @classmethod
    def _interval_energy_series_to_average_power_series(cls, source: TES_2025a) -> TES_2025a:
        # Gn/Lod forecast inputs are interval energy (Wh per slot) derived from
        # meter deltas; the optimization model works on average power (W).
        sample_rate_hours = cls._resolved_series_sample_rate_hours(source)
        if sample_rate_hours <= 0:
            return cls._clone_series_with_values(source, list(source.val))

        normalized_values = []
        for value in source.val:
            if value is None:
                normalized_values.append(None)
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                normalized_values.append(value)
                continue
            if not math.isfinite(numeric_value):
                normalized_values.append(value)
                continue
            normalized_values.append(numeric_value / sample_rate_hours)

        return cls._clone_series_with_values(source, normalized_values)

    @staticmethod
    def _series_horizon_length(series: TES_2025a) -> int:
        return series.smpNum or len(series.val)

    @staticmethod
    def _charge_bounds_for_step(
        net_power: float,
        charge_limit: float,
        active_alpha_one_constraint: bool,
    ) -> tuple[float, float]:
        if not active_alpha_one_constraint:
            return charge_limit, 0.0
        if net_power <= 0:
            return 0.0, 0.0
        return max(charge_limit, -net_power), 0.0

    def _diagnose_bess_inputs(
        self,
        *,
        label: str,
        gn_forecast: list,
        lod_forecast: list,
        dam_price_forecast: list,
        soc_wh: float,
        use_wh: float,
        use_wh_min_pct: float,
        use_wh_max_pct: float,
        cha_w_max: float,
        dsch_w_max: float,
        cha_efc: float,
        dsch_efc: float,
        dcsc_cntt_watt: float,
        dprc_cntt_watt: float,
        sample_rate_hours: float,
        active_alpha_one_constraint: bool,
    ) -> list[str]:
        causes: list[str] = []
        horizon = min(len(gn_forecast), len(lod_forecast), len(dam_price_forecast))

        if horizon <= 0:
            causes.append(f"{label}: optimization horizon is empty because one or more forecasts have no samples.")
            return causes

        gn_non_finite = [t for t in range(horizon) if not self._is_finite_forecast_value(gn_forecast[t])]
        lod_non_finite = [t for t in range(horizon) if not self._is_finite_forecast_value(lod_forecast[t])]
        dam_non_finite = [t for t in range(horizon) if not self._is_finite_forecast_value(dam_price_forecast[t])]
        gn_negative = [
            t for t in range(horizon) if self._is_finite_forecast_value(gn_forecast[t]) and float(gn_forecast[t]) < 0
        ]
        lod_positive = [
            t for t in range(horizon) if self._is_finite_forecast_value(lod_forecast[t]) and float(lod_forecast[t]) > 0
        ]

        if gn_non_finite:
            causes.append(
                f"{label}: generation forecast contains non-finite samples at indices "
                f"{self._summarize_indices(gn_non_finite)}."
            )
        if lod_non_finite:
            causes.append(
                f"{label}: load forecast contains non-finite samples at indices "
                f"{self._summarize_indices(lod_non_finite)}."
            )
        if dam_non_finite:
            causes.append(
                f"{label}: DAM price forecast contains non-finite samples at indices "
                f"{self._summarize_indices(dam_non_finite)}."
            )
        if gn_negative:
            causes.append(
                f"{label}: generation forecast has negative samples at indices "
                f"{self._summarize_indices(gn_negative)}; this model expects generation >= 0."
            )
        if lod_positive:
            causes.append(
                f"{label}: load forecast has positive samples at indices "
                f"{self._summarize_indices(lod_positive)}; this model expects load <= 0."
            )

        if cha_w_max > 0:
            causes.append(f"{label}: ChaWMax={cha_w_max} is positive; charging power must be configured as <= 0.")
        if dsch_w_max < 0:
            causes.append(f"{label}: DschWMax={dsch_w_max} is negative; discharge power must be configured as >= 0.")
        if use_wh <= 0:
            causes.append(f"{label}: UseWh={use_wh} must be strictly positive.")
        if use_wh_min_pct < 0 or use_wh_max_pct < 0:
            causes.append(f"{label}: UseWhMinPct={use_wh_min_pct} and UseWhMaxPct={use_wh_max_pct} must be >= 0.")
        if use_wh_min_pct > use_wh_max_pct:
            causes.append(f"{label}: UseWhMinPct={use_wh_min_pct} is greater than UseWhMaxPct={use_wh_max_pct}.")
        if use_wh_max_pct > 100:
            causes.append(f"{label}: UseWhMaxPct={use_wh_max_pct} exceeds 100%; the SoE upper bound is inconsistent.")
        if dcsc_cntt_watt < 0 or dprc_cntt_watt < 0:
            causes.append(
                f"{label}: contract power limits must be >= 0; got "
                f"CnttWatt withdraw={dcsc_cntt_watt}, feed={dprc_cntt_watt}."
            )
        if sample_rate_hours <= 0:
            causes.append(f"{label}: sample rate must be > 0 hours; got {sample_rate_hours}.")
        if cha_efc <= 0 or dsch_efc <= 0:
            causes.append(f"{label}: efficiencies must be > 0; got ChaEfc={cha_efc}, DschEfc={dsch_efc}.")

        soc_min = use_wh * use_wh_min_pct / 100
        soc_max = use_wh * use_wh_max_pct / 100
        if soc_wh < soc_min or soc_wh > soc_max:
            causes.append(
                f"{label}: initial SocWh={soc_wh} Wh is outside the allowed range [{soc_min}, {soc_max}] Wh."
            )

        contract_min = -dcsc_cntt_watt
        contract_max = dprc_cntt_watt
        balance_conflicts: list[str] = []
        for t in range(horizon):
            if not (
                self._is_finite_forecast_value(gn_forecast[t]) and self._is_finite_forecast_value(lod_forecast[t])
            ):
                continue

            net_power = float(gn_forecast[t]) + float(lod_forecast[t])
            charge_min, _charge_max = self._charge_bounds_for_step(
                net_power,
                cha_w_max,
                active_alpha_one_constraint,
            )
            feasible_grid_min = net_power + charge_min
            feasible_grid_max = net_power + dsch_w_max
            if feasible_grid_max < contract_min or feasible_grid_min > contract_max:
                balance_conflicts.append(
                    f"t={t}: net={net_power} W, feasible grid range=[{feasible_grid_min}, {feasible_grid_max}] W, "
                    f"contract range=[{contract_min}, {contract_max}] W"
                )

        if balance_conflicts:
            causes.append(
                f"{label}: forecast/contract/battery limits are incompatible for "
                f"{len(balance_conflicts)} timestep(s): {'; '.join(balance_conflicts[:3])}"
                f"{'...' if len(balance_conflicts) > 3 else ''}."
            )

        if (
            sample_rate_hours > 0
            and cha_efc > 0
            and dsch_efc > 0
            and self._is_finite_forecast_value(gn_forecast[0])
            and self._is_finite_forecast_value(lod_forecast[0])
        ):
            net0 = float(gn_forecast[0]) + float(lod_forecast[0])
            charge_min0, _charge_max0 = self._charge_bounds_for_step(
                net0,
                cha_w_max,
                active_alpha_one_constraint,
            )
            min_soe_after_t0 = soc_wh - (dsch_w_max / dsch_efc) * sample_rate_hours
            max_soe_after_t0 = soc_wh - charge_min0 * cha_efc * sample_rate_hours
            if max_soe_after_t0 < soc_min or min_soe_after_t0 > soc_max:
                causes.append(
                    f"{label}: the first optimization step cannot keep SoE inside [{soc_min}, {soc_max}] Wh; "
                    f"reachable SoE after t=0 is [{min_soe_after_t0}, {max_soe_after_t0}] Wh."
                )

            required_battery_min = contract_min - net0
            required_battery_max = contract_max - net0
            if required_battery_min > 0 and soc_wh <= soc_min:
                causes.append(
                    f"{label}: t=0 requires battery discharge to respect the withdrawal limit, "
                    f"but SocWh={soc_wh} Wh is already at/below the minimum {soc_min} Wh."
                )
            if required_battery_max < 0 and soc_wh >= soc_max:
                causes.append(
                    f"{label}: t=0 requires battery charge to respect the feed-in limit, "
                    f"but SocWh={soc_wh} Wh is already at/above the maximum {soc_max} Wh."
                )

        return causes

    def _diagnose_sc_ea_1bess_infeasibility(self, model: "OptProb_SC_EA_1BESS", user_label: str) -> list[str]:
        causes = self._diagnose_bess_inputs(
            label=f"user '{user_label}'",
            gn_forecast=model.GnFrcst,
            lod_forecast=model.LodFrcst,
            dam_price_forecast=model.DamPrcFrcst,
            soc_wh=model.SocWh,
            use_wh=model.UseWh,
            use_wh_min_pct=model.UseWhMinPct,
            use_wh_max_pct=model.UseWhMaxPct,
            cha_w_max=model.ChaWMax,
            dsch_w_max=model.DschWMax,
            cha_efc=model.ChaEfc,
            dsch_efc=model.DschEfc,
            dcsc_cntt_watt=model.DcscCnttWatt,
            dprc_cntt_watt=model.DprcCnttWatt,
            sample_rate_hours=model.WtoWhConversion,
            active_alpha_one_constraint=model.ActiveAlphaOneConstraintRule,
        )
        if causes:
            return causes
        return [
            f"user '{user_label}': no obvious sign or parameter inconsistency was detected; "
            "inspect the full forecast horizon and the solver log for a tighter IIS-style diagnosis."
        ]

    def _diagnose_raw_bess_inputs(
        self,
        *,
        user_label: str,
        incl_der: ORG_DMDR_2025a,
        gn_forecast: TES_2025a,
        lod_forecast: TES_2025a,
        dam_price_forecast: TES_2025a,
        active_alpha_one_constraint: bool,
    ) -> list[str]:
        gn_rate = self._resolved_series_sample_rate(gn_forecast)
        lod_rate = self._resolved_series_sample_rate(lod_forecast)
        dam_rate = self._resolved_series_sample_rate(dam_price_forecast)
        gn_power_forecast = self._interval_energy_series_to_average_power_series(gn_forecast)
        lod_power_forecast = self._interval_energy_series_to_average_power_series(lod_forecast)
        causes: list[str] = []

        if gn_rate != lod_rate or gn_rate != dam_rate:
            causes.append(
                f"user '{user_label}': forecast sample rates are inconsistent "
                f"(generation={gn_rate}, load={lod_rate}, DAM={dam_rate})."
            )

        causes.extend(
            self._diagnose_bess_inputs(
                label=f"user '{user_label}'",
                gn_forecast=gn_power_forecast.val,
                lod_forecast=lod_power_forecast.val,
                dam_price_forecast=dam_price_forecast.val,
                soc_wh=incl_der.setSrcRef.InclSto.setSrcRef.SocWh.mag,
                use_wh=incl_der.setSrcRef.InclSto.setSrcRef.UseWh.setMag,
                use_wh_min_pct=incl_der.setSrcRef.InclSto.setSrcRef.UseWhMinPct.setMag,
                use_wh_max_pct=incl_der.setSrcRef.InclSto.setSrcRef.UseWhMaxPct.setMag,
                cha_w_max=incl_der.setSrcRef.InclSto.setSrcRef.ChaWMax.setMag,
                dsch_w_max=incl_der.setSrcRef.InclSto.setSrcRef.DschWMax.setMag,
                cha_efc=(
                    incl_der.setSrcRef.InclSto.setSrcRef.ChaEfcPct.setMag / 100.0
                    if incl_der.setSrcRef.InclSto.setSrcRef.ChaEfcPct.setMag > 0
                    else 0.96
                ),
                dsch_efc=(
                    incl_der.setSrcRef.InclSto.setSrcRef.DschEfcPct.setMag / 100.0
                    if incl_der.setSrcRef.InclSto.setSrcRef.DschEfcPct.setMag > 0
                    else 0.96
                ),
                dcsc_cntt_watt=incl_der.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.CnttWatt.setMag,
                dprc_cntt_watt=incl_der.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.CnttWatt.setMag,
                sample_rate_hours=gn_rate.total_seconds() / 3600,
                active_alpha_one_constraint=active_alpha_one_constraint,
            )
        )
        return causes

    def _diagnose_csc_sc_ea_mbess_infeasibility(
        self,
        model: "OptProb_CSC_SC_EA_mBESS",
        user_labels: dict[int, str],
    ) -> list[str]:
        causes: list[str] = []
        for user_id in model.UserIndices:
            user_label = user_labels.get(cast(int, user_id), str(user_id))
            user_causes = self._diagnose_bess_inputs(
                label=f"user '{user_label}'",
                gn_forecast=getattr(model, f"GnFrcst_{user_id}"),
                lod_forecast=getattr(model, f"LodFrcst_{user_id}"),
                dam_price_forecast=getattr(model, f"DamPrcFrcst_{user_id}"),
                soc_wh=getattr(model, f"SocWh_{user_id}"),
                use_wh=getattr(model, f"UseWh_{user_id}"),
                use_wh_min_pct=getattr(model, f"UseWhMinPct_{user_id}"),
                use_wh_max_pct=getattr(model, f"UseWhMaxPct_{user_id}"),
                cha_w_max=getattr(model, f"ChaWMax_{user_id}"),
                dsch_w_max=getattr(model, f"DschWMax_{user_id}"),
                cha_efc=getattr(model, f"ChaEfc_{user_id}"),
                dsch_efc=getattr(model, f"DschEfc_{user_id}"),
                dcsc_cntt_watt=getattr(model, f"DcscCnttWatt_{user_id}"),
                dprc_cntt_watt=getattr(model, f"DprcCnttWatt_{user_id}"),
                sample_rate_hours=model.WtoWhConversion,
                active_alpha_one_constraint=model.ActiveAlphaOneConstraintRule,
            )
            causes.extend(user_causes)

        if causes:
            return causes
        return [
            "CSC optimization: no obvious per-user sign or parameter inconsistency was detected; "
            "inspect the combined horizon and solver log for a tighter IIS-style diagnosis."
        ]

    def _diagnose_csc_raw_inputs(
        self,
        users_data: dict[int, dict],
        active_alpha_one_constraint: bool,
    ) -> list[str]:
        causes: list[str] = []
        reference_rate: timedelta | None = None
        reference_horizon: int | None = None
        for user_id, data in users_data.items():
            user_label = data["InclDER"].setSrcRef.OutEcpRef.setSrcRef.AreaEpsEcpId.dataNs
            causes.extend(
                self._diagnose_raw_bess_inputs(
                    user_label=user_label,
                    incl_der=data["InclDER"],
                    gn_forecast=data["GnFrcst"],
                    lod_forecast=data["LodFrcst"],
                    dam_price_forecast=data["DamPrcFrcst"],
                    active_alpha_one_constraint=active_alpha_one_constraint,
                )
            )
            user_rate = self._resolved_series_sample_rate(data["LodFrcst"])
            user_horizon = self._series_horizon_length(data["LodFrcst"])
            if reference_rate is None:
                reference_rate = user_rate
                reference_horizon = user_horizon
                continue
            if user_rate != reference_rate:
                causes.append(
                    f"CSC optimization: user '{user_label}' has sample rate {user_rate}, "
                    f"while the reference rate is {reference_rate}."
                )
            if user_horizon != reference_horizon:
                causes.append(
                    f"CSC optimization: user '{user_label}' has horizon {user_horizon} samples, "
                    f"while the reference horizon is {reference_horizon}."
                )
        return causes

    def _log_precheck_failure(self, context: str, causes: list[str]) -> None:
        self._logger.warning(
            f"[DPMC_ERAB] Optimization {context} skipped before solve because pre-check found "
            f"{len(causes)} blocking issue(s)."
        )
        for cause in causes:
            self._logger.warning(f"[DPMC_ERAB] Optimization {context} pre-check cause: {cause}")

    def _log_csc_participant_downgrade(self, user_label: str, causes: list[str]) -> None:
        self._logger.warning(
            f"[DPMC_ERAB] CSC participant user '{user_label}' moved from active to passive group "
            f"because pre-check found {len(causes)} blocking issue(s)."
        )
        for cause in causes:
            self._logger.warning(f"[DPMC_ERAB] CSC participant user '{user_label}' passive downgrade cause: {cause}")

    @staticmethod
    def _set_setpoint_invalid_if_available(bess_dpmc_ref: ORG_DPMC_2025a | None) -> None:
        if bess_dpmc_ref is None:
            return
        bess_dpmc_ref.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.invalid

    def _get_bess_dpmc_ref(self, index: int, *, required: bool) -> ORG_DPMC_2025a | None:
        bess_dpmc_ref = getattr(self, f"BessDpmcRef{index}", None)
        if bess_dpmc_ref is None:
            if required:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'BessDpmcRef{index}'")
            return None
        if getattr(bess_dpmc_ref, "setSrcRef", None) is None:
            if required:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'setSrcRef'")
            return None
        return cast(ORG_DPMC_2025a, bess_dpmc_ref)

    def _add_csc_passive_participant(
        self,
        *,
        user_label: str,
        gn_forecast: TES_2025a,
        lod_forecast: TES_2025a,
        passive_fed: TES_2025a,
        passive_withdrawn: TES_2025a,
    ) -> bool:
        gn_rate = self._resolved_series_sample_rate(gn_forecast)
        lod_rate = self._resolved_series_sample_rate(lod_forecast)
        gn_horizon = self._series_horizon_length(gn_forecast)
        lod_horizon = self._series_horizon_length(lod_forecast)

        if gn_rate != lod_rate or gn_horizon != lod_horizon:
            self._logger.warning(
                f"[DPMC_ERAB] CSC passive aggregation skipped for user '{user_label}' because "
                f"generation/load forecasts are inconsistent (generation={gn_horizon}@{gn_rate}, "
                f"load={lod_horizon}@{lod_rate})."
            )
            return False

        if passive_withdrawn.val == []:
            passive_fed.val = [0.0] * lod_horizon
            passive_withdrawn.val = [0.0] * lod_horizon
            passive_fed.smpNum = lod_horizon
            passive_withdrawn.smpNum = lod_horizon
            passive_fed.smpRate = lod_forecast.smpRate
            passive_withdrawn.smpRate = lod_forecast.smpRate
            passive_fed.t = lod_forecast.t
            passive_withdrawn.t = lod_forecast.t
        else:
            passive_rate = self._resolved_series_sample_rate(passive_withdrawn)
            passive_horizon = self._series_horizon_length(passive_withdrawn)
            if passive_rate != lod_rate or passive_horizon != lod_horizon:
                self._logger.warning(
                    f"[DPMC_ERAB] CSC passive aggregation skipped for user '{user_label}' because "
                    f"its forecast shape ({lod_horizon}@{lod_rate}) does not match the existing passive "
                    f"profile ({passive_horizon}@{passive_rate})."
                )
                return False

        for step in range(lod_horizon):
            if not (
                self._is_finite_forecast_value(gn_forecast.val[step])
                and self._is_finite_forecast_value(lod_forecast.val[step])
            ):
                self._logger.warning(
                    f"[DPMC_ERAB] CSC passive aggregation skipped for user '{user_label}' because "
                    f"its forecasts contain non-finite samples at step {step}."
                )
                return False

            net_value = float(gn_forecast.val[step]) + float(lod_forecast.val[step])
            if net_value > 0:
                passive_fed.val[step] += net_value
            else:
                passive_withdrawn.val[step] += net_value

        return True

    def _handle_solver_results(
        self,
        *,
        model: ConcreteModel,
        results: Any,
        context: str,
        diagnose_infeasible: Callable[[], list[str]] | None = None,
    ) -> bool:
        solver = getattr(results, "solver", None)
        status = getattr(solver, "status", "<unknown>")
        termination = getattr(solver, "termination_condition", "<unknown>")
        message = getattr(solver, "message", None) or "<undefined>"

        infeasible_like_terminations = {
            TerminationCondition.infeasible,
            TerminationCondition.infeasibleOrUnbounded,
            TerminationCondition.invalidProblem,
        }

        if self._solver_result_has_solution(results) and termination not in infeasible_like_terminations:
            try:
                model.solutions.load_from(results)
                return True
            except Exception as exc:
                self._logger.warning(
                    f"[DPMC_ERAB] Optimization {context} returned a solution object that could not be loaded: {exc}"
                )
                return False

        self._logger.warning(
            f"[DPMC_ERAB] Optimization {context} returned no usable solution. "
            f"status={status}; termination={termination}; message={message}"
        )
        if termination in infeasible_like_terminations and diagnose_infeasible is not None:
            for cause in diagnose_infeasible():
                self._logger.warning(f"[DPMC_ERAB] Optimization {context} infeasible cause: {cause}")

        return False

    def __call__(self) -> None:

        CSC_active_partecipants_data = {}
        CSC_passive_partecipants_fed = TES_2025a()
        CSC_passive_partecipants_withdrawn = TES_2025a()

        for i in range(1, self._visitor.get_users_length() + 1):

            InclDER = getattr(self.DERRef.setSrcRef, f"InclDER{i}", None)
            if InclDER is None:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'InclDER{i}'")
            if getattr(InclDER, "setSrcRef", None) is None:
                continue
            InclDER = cast(ORG_DMDR_2025a, InclDER)

            WhichLogic = getattr(self, f"WhichLogic{i}", None)
            if WhichLogic is None:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'WhichLogic{i}'")
            if getattr(WhichLogic, "dataNs", None) is None:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'dataNs'")
            WhichLogic = cast(VSG_2025a, WhichLogic)

            UserId = InclDER.setSrcRef.OutEcpRef.setSrcRef.AreaEpsEcpId.dataNs
            ZoneID = InclDER.setSrcRef.OutEcpRef.setSrcRef.AreaEpsMrkZnId.dataNs

            WhichControl = getattr(self, f"WhichControl{i}", None)
            if WhichControl is None:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'WhichControl{i}'")
            if getattr(WhichControl, "dataNs", None) is None:
                raise AttributeError(f"{self.__class__.__name__} has no attribute 'dataNs'")
            WhichControl = cast(VSG_2025a, WhichControl)
            is_bess_optimization_logic = WhichLogic.dataNs in {"SC_EA_1BESS", "CSC_SC_EA_mBESS"}
            bess_dpmc_ref = self._get_bess_dpmc_ref(i, required=False) if is_bess_optimization_logic else None

            if WhichControl.dataNs == "Unavailable":
                self._logger.debug(
                    f"[DPMC_ERAB] WhichControl for user '{UserId}' is 'Unavailable'. Skipping user {i}."
                )
                continue

            # Retrieve forecasts with error handling
            try:
                LodFrcst = self.FrcsRefLOD.setSrcRef.LodEnTotFrcs[UserId]
            except KeyError:
                self._logger.warning(f"[DPMC_ERAB] Load forecast not found for user '{UserId}'. Skipping user {i}.")
                self._set_setpoint_invalid_if_available(bess_dpmc_ref)
                continue

            try:
                GnFrcst = self.FrcsRefGN.setSrcRef.GnEnTotFrcs[UserId]
            except KeyError:
                GnFrcst = TES_2025a()
                GnFrcst.val = [0.0] * LodFrcst.smpNum
                GnFrcst.smpRate = LodFrcst.smpRate
                GnFrcst.smpNum = LodFrcst.smpNum
                self._logger.debug(
                    f"[DPMC_ERAB] Generation forecast not found for user '{UserId}'. Using zero generation."
                )

            try:
                DamPrcFrcst = self.FrcsRefDAM.setSrcRef.DamPrcFrcs[ZoneID]
            except KeyError:
                self._logger.warning(
                    f"[DPMC_ERAB] DAM price forecast not found for zone '{ZoneID}'. Skipping user {i} ('{UserId}')."
                )
                self._set_setpoint_invalid_if_available(bess_dpmc_ref)
                continue

            # Validate forecast quality before using
            if not self._check_forecast_validity(LodFrcst, "Load forecast", UserId):
                self._set_setpoint_invalid_if_available(bess_dpmc_ref)
                continue
            if not self._check_forecast_validity(DamPrcFrcst, "DAM price forecast", f"{UserId} (zone {ZoneID})"):
                self._set_setpoint_invalid_if_available(bess_dpmc_ref)
                continue
            if not self._check_forecast_validity(GnFrcst, "Generation forecast", UserId):
                self._set_setpoint_invalid_if_available(bess_dpmc_ref)
                continue

            if WhichLogic.dataNs == "SC_EA_1BESS" or WhichLogic.dataNs == "CSC_SC_EA_mBESS":

                BessDpmcRef = bess_dpmc_ref or self._get_bess_dpmc_ref(i, required=True)

                if WhichLogic.dataNs == "SC_EA_1BESS":
                    self.Scheduler_SC_EA_1BESS(
                        InclDER=InclDER,
                        BessDpmcRef=BessDpmcRef,
                        GnFrcst=GnFrcst,
                        LodFrcst=LodFrcst,
                        DamPrcFrcst=DamPrcFrcst,
                    )
                    continue

                elif WhichLogic.dataNs == "CSC_SC_EA_mBESS":
                    participant_precheck_causes = self._diagnose_raw_bess_inputs(
                        user_label=UserId,
                        incl_der=InclDER,
                        gn_forecast=GnFrcst,
                        lod_forecast=LodFrcst,
                        dam_price_forecast=DamPrcFrcst,
                        active_alpha_one_constraint=True,
                    )
                    if participant_precheck_causes:
                        self._log_csc_participant_downgrade(UserId, participant_precheck_causes)
                        self._set_setpoint_invalid_if_available(BessDpmcRef)
                        self._add_csc_passive_participant(
                            user_label=UserId,
                            gn_forecast=GnFrcst,
                            lod_forecast=LodFrcst,
                            passive_fed=CSC_passive_partecipants_fed,
                            passive_withdrawn=CSC_passive_partecipants_withdrawn,
                        )
                        continue

                    CSC_active_partecipants_data[i] = {
                        "InclDER": InclDER,
                        "BessDpmcRef": BessDpmcRef,
                        "GnFrcst": GnFrcst,
                        "LodFrcst": LodFrcst,
                        "DamPrcFrcst": DamPrcFrcst,
                    }

            elif WhichLogic.dataNs == "CSC_NotControllable":
                self._add_csc_passive_participant(
                    user_label=UserId,
                    gn_forecast=GnFrcst,
                    lod_forecast=LodFrcst,
                    passive_fed=CSC_passive_partecipants_fed,
                    passive_withdrawn=CSC_passive_partecipants_withdrawn,
                )

        if CSC_active_partecipants_data != {}:
            self.Scheduler_CSC_SC_EA_mBESS(
                CSC_active_partecipants_data=CSC_active_partecipants_data,
                CSC_passive_partecipants_fed=CSC_passive_partecipants_fed,
                CSC_passive_partecipants_withdrawn=CSC_passive_partecipants_withdrawn,
            )

    def Scheduler_SC_EA_1BESS(
        self,
        InclDER: ORG_DMDR_2025a,
        BessDpmcRef: ORG_DPMC_2025a,
        GnFrcst: TES_2025a,
        LodFrcst: TES_2025a,
        DamPrcFrcst: TES_2025a,
        ActiveAlphaOneConstraintRule: bool = True,
    ) -> None:
        """Scheduler based on optimization for the SC_EA_1BESS logic"""
        user_label = InclDER.setSrcRef.OutEcpRef.setSrcRef.AreaEpsEcpId.dataNs
        gn_power_forecast = self._interval_energy_series_to_average_power_series(GnFrcst)
        lod_power_forecast = self._interval_energy_series_to_average_power_series(LodFrcst)
        precheck_causes = self._diagnose_raw_bess_inputs(
            user_label=user_label,
            incl_der=InclDER,
            gn_forecast=GnFrcst,
            lod_forecast=LodFrcst,
            dam_price_forecast=DamPrcFrcst,
            active_alpha_one_constraint=ActiveAlphaOneConstraintRule,
        )
        if precheck_causes:
            self._log_precheck_failure(
                context=f"SC_EA_1BESS for user '{user_label}'",
                causes=precheck_causes,
            )
            BessDpmcRef.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.invalid
            return

        OptProb = OptProb_SC_EA_1BESS(
            GnFrcst=gn_power_forecast,
            LodFrcst=lod_power_forecast,
            DamPrcFrcst=DamPrcFrcst,
            InclDER=InclDER,
            ActiveAlphaOneConstraintRule=ActiveAlphaOneConstraintRule,
        )
        OptProb = cast(OptProb_SC_EA_1BESS, OptProb)

        solver = SolverFactory("cbc", executable=self._resolve_cbc_executable())
        solver.options["ratioGap"] = 0.01  # Ferma il solver se la differenza relativa è inferiore all 1%
        solver.options["allowableGap"] = 0.1  # Ferma il solver se la differenza assoluta è minore di 0.1
        solver.options["seconds"] = 10  # Ferma il solver se non converge in uno step
        solver.options["primalTolerance"] = 1e-6  # Precisione sui valori delle variabili
        solver.options["dualTolerance"] = 1e-6  # Precisione sui moltiplicatori di lagrange (ottimalità duale)

        results = solver.solve(OptProb, tee=False, logfile=None, load_solutions=False)
        # solver.solve(model, tee=True) # Debugging
        if not self._handle_solver_results(
            model=OptProb,
            results=results,
            context=f"SC_EA_1BESS for user '{user_label}'",
            diagnose_infeasible=lambda: self._diagnose_sc_ea_1bess_infeasibility(OptProb, user_label),
        ):
            BessDpmcRef.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.invalid
            return

        # Solutions
        Cha = [value(OptProb.WCharge[q]) for q in OptProb.WCharge]
        Dsch = [value(OptProb.WDischarge[q]) for q in OptProb.WDischarge]
        ReqW_opt = cast(list, Cha)[0] + Dsch[0]

        # Compute DiffWSpt respect to SC-rule-based (WSptRB)
        FolWRef = OptProb.GnFrcst[0] + OptProb.LodFrcst[0]
        FolWTgt = BessDpmcRef.setSrcRef.FctRef1.setSrcRef.FolWTgt.setMag
        WThr = BessDpmcRef.setSrcRef.FctRef1.setSrcRef.WThr.setMag
        WPct = BessDpmcRef.setSrcRef.FctRef1.setSrcRef.WPct.setMag
        if abs(FolWRef - FolWTgt) > WThr:
            WSptRB = -WPct * (FolWRef - FolWTgt) / 100.0
        else:
            WSptRB = 0
        if WSptRB > 0.0:
            if (
                InclDER.setSrcRef.InclSto.setSrcRef.SocWh.mag
                > InclDER.setSrcRef.InclSto.setSrcRef.UseWh.setMag
                * InclDER.setSrcRef.InclSto.setSrcRef.UseWhMinPct.setMag
                / 100.0
            ):
                WSptRB = min(WSptRB, InclDER.setSrcRef.InclSto.setSrcRef.DschWMax.setMag)
            else:
                WSptRB = 0.0
        else:
            if (
                InclDER.setSrcRef.InclSto.setSrcRef.SocWh.mag
                < InclDER.setSrcRef.InclSto.setSrcRef.UseWh.setMag
                * InclDER.setSrcRef.InclSto.setSrcRef.UseWhMaxPct.setMag
                / 100.0
            ):
                WSptRB = max(WSptRB, InclDER.setSrcRef.InclSto.setSrcRef.ChaWMax.setMag)
            else:
                WSptRB = 0.0

        # If the optimization result is materially different from rule-based control,
        # expose it as GOOD. Otherwise keep the optimized value but mark it QUESTIONABLE
        # so downstream logic can ignore it while preserving observability.
        if abs(ReqW_opt - WSptRB) > 100.0:
            BessDpmcRef.setSrcRef.WSpt2.Operate(ReqW_opt)
            BessDpmcRef.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.good
        else:
            BessDpmcRef.setSrcRef.WSpt2.Operate(ReqW_opt)
            BessDpmcRef.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.questionable

        # WWithdrawn = [value(OptProb.WWithdrawn[q]) for q in OptProb.WWithdrawn]
        # WFed = [value(OptProb.WFed[q]) for q in OptProb.WFed]
        SoE = [value(OptProb.WhStateOfEnergy[q]) for q in OptProb.WhStateOfEnergy]
        self.SoE1 = SoE
        # return SoE, Cha, Dsch, WWithdrawn, WFed, self.ReqW[self.UserId].mag
        return

    def Scheduler_CSC_SC_EA_mBESS(
        self,
        CSC_active_partecipants_data: dict[int, dict],
        CSC_passive_partecipants_fed: TES_2025a,
        CSC_passive_partecipants_withdrawn: TES_2025a,
        ActiveAlphaOneConstraintRule: bool = True,
    ) -> None:
        """Scheduler based on optimization for the CSC_SC_EA_mBESS logic"""
        user_labels = {
            user_id: data["InclDER"].setSrcRef.OutEcpRef.setSrcRef.AreaEpsEcpId.dataNs
            for user_id, data in CSC_active_partecipants_data.items()
        }
        normalized_users_data = {
            user_id: {
                **data,
                "GnFrcst": self._interval_energy_series_to_average_power_series(data["GnFrcst"]),
                "LodFrcst": self._interval_energy_series_to_average_power_series(data["LodFrcst"]),
            }
            for user_id, data in CSC_active_partecipants_data.items()
        }
        passive_fed_power = self._interval_energy_series_to_average_power_series(CSC_passive_partecipants_fed)
        passive_withdrawn_power = self._interval_energy_series_to_average_power_series(
            CSC_passive_partecipants_withdrawn
        )
        precheck_causes = self._diagnose_csc_raw_inputs(
            users_data=CSC_active_partecipants_data,
            active_alpha_one_constraint=ActiveAlphaOneConstraintRule,
        )
        reference_rate = None
        if normalized_users_data:
            first_user_data = next(iter(normalized_users_data.values()))
            reference_rate = self._resolved_series_sample_rate(first_user_data["LodFrcst"])
            if self._resolved_series_sample_rate(passive_fed_power) != reference_rate:
                precheck_causes.append(
                    f"CSC optimization: passive fed profile has sample rate "
                    f"{self._resolved_series_sample_rate(passive_fed_power)}, expected {reference_rate}."
                )
            if self._resolved_series_sample_rate(passive_withdrawn_power) != reference_rate:
                precheck_causes.append(
                    f"CSC optimization: passive withdrawn profile has sample rate "
                    f"{self._resolved_series_sample_rate(passive_withdrawn_power)}, expected {reference_rate}."
                )
        if precheck_causes:
            self._log_precheck_failure(
                context=f"CSC_SC_EA_mBESS for users {list(user_labels.values())}",
                causes=precheck_causes,
            )
            for user_data in CSC_active_partecipants_data.values():
                user_data["BessDpmcRef"].setSrcRef.WSpt2.q.validity = ValidityKind_2025a.invalid
            return

        # Create and solve optimization problem
        OptProb = OptProb_CSC_SC_EA_mBESS(
            users_data=normalized_users_data,
            CSC_passive_partecipants_fed=passive_fed_power,
            CSC_passive_partecipants_withdrawn=passive_withdrawn_power,
            ActiveAlphaOneConstraintRule=ActiveAlphaOneConstraintRule,
        )
        OptProb = cast(OptProb_CSC_SC_EA_mBESS, OptProb)

        # Configure and solve
        solver = SolverFactory("cbc", executable=self._resolve_cbc_executable())
        solver.options["ratioGap"] = 0.01
        solver.options["allowableGap"] = 0.1
        solver.options["seconds"] = 10
        solver.options["primalTolerance"] = 1e-6
        solver.options["dualTolerance"] = 1e-6

        results = solver.solve(OptProb, tee=False, logfile=None, load_solutions=False)
        if not self._handle_solver_results(
            model=OptProb,
            results=results,
            context=f"CSC_SC_EA_mBESS for users {list(user_labels.values())}",
            diagnose_infeasible=lambda: self._diagnose_csc_sc_ea_mbess_infeasibility(OptProb, user_labels),
        ):
            for user_data in CSC_active_partecipants_data.values():
                user_data["BessDpmcRef"].setSrcRef.WSpt2.q.validity = ValidityKind_2025a.invalid
            return

        # Distribute results to each user
        for user_id, user_data in normalized_users_data.items():
            # Get results for this user (first time sample as setpoint)
            Cha = value(OptProb.WCharge[user_id, 0])
            Dsch = value(OptProb.WDischarge[user_id, 0])
            ReqW_opt = cast(float, Cha) + cast(float, Dsch)

            # Extract user references
            BessDpmcRef = user_data["BessDpmcRef"]
            InclDER = user_data["InclDER"]
            GnFrcst = user_data["GnFrcst"]
            LodFrcst = user_data["LodFrcst"]

            # Compute DiffWSpt respect to SC-rule-based (WSptRB)
            FolWRef = GnFrcst.val[0] + LodFrcst.val[0]
            FolWTgt = BessDpmcRef.setSrcRef.FctRef1.setSrcRef.FolWTgt.setMag
            WThr = BessDpmcRef.setSrcRef.FctRef1.setSrcRef.WThr.setMag
            WPct = BessDpmcRef.setSrcRef.FctRef1.setSrcRef.WPct.setMag

            if abs(FolWRef - FolWTgt) > WThr:
                WSptRB = -WPct * (FolWRef - FolWTgt) / 100.0
            else:
                WSptRB = 0.0

            if WSptRB > 0.0:
                if (
                    InclDER.setSrcRef.InclSto.setSrcRef.SocWh.mag
                    > InclDER.setSrcRef.InclSto.setSrcRef.UseWh.setMag
                    * InclDER.setSrcRef.InclSto.setSrcRef.UseWhMinPct.setMag
                    / 100.0
                ):
                    WSptRB = min(WSptRB, InclDER.setSrcRef.InclSto.setSrcRef.DschWMax.setMag)
                else:
                    WSptRB = 0.0
            else:
                if (
                    InclDER.setSrcRef.InclSto.setSrcRef.SocWh.mag
                    < InclDER.setSrcRef.InclSto.setSrcRef.UseWh.setMag
                    * InclDER.setSrcRef.InclSto.setSrcRef.UseWhMaxPct.setMag
                    / 100.0
                ):
                    WSptRB = max(WSptRB, InclDER.setSrcRef.InclSto.setSrcRef.ChaWMax.setMag)
                else:
                    WSptRB = 0.0

            # If the optimization result is materially different from rule-based control,
            # expose it as GOOD. Otherwise keep the optimized value but mark it QUESTIONABLE
            # so downstream logic can ignore it while preserving observability.
            if abs(ReqW_opt - WSptRB) > 100.0:
                BessDpmcRef.setSrcRef.WSpt2.Operate(ReqW_opt)
                BessDpmcRef.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.good
            else:
                BessDpmcRef.setSrcRef.WSpt2.Operate(ReqW_opt)
                BessDpmcRef.setSrcRef.WSpt2.q.validity = ValidityKind_2025a.questionable

        return


class OptProb_SC_EA_1BESS(ConcreteModel):
    def __init__(
        self,
        GnFrcst: TES_2025a,
        DamPrcFrcst: TES_2025a,
        LodFrcst: TES_2025a,
        InclDER: ORG_DMDR_2025a,
        ActiveAlphaOneConstraintRule: bool,
    ):
        super().__init__()

        # forecasts
        self.GnFrcst = GnFrcst.val
        self.DamPrcFrcst = DamPrcFrcst.val
        self.LodFrcst = LodFrcst.val

        # bess parameters
        self.SocWh = InclDER.setSrcRef.InclSto.setSrcRef.SocWh.mag
        self.UseWh = InclDER.setSrcRef.InclSto.setSrcRef.UseWh.setMag
        self.UseWhMinPct = InclDER.setSrcRef.InclSto.setSrcRef.UseWhMinPct.setMag
        self.UseWhMaxPct = InclDER.setSrcRef.InclSto.setSrcRef.UseWhMaxPct.setMag
        self.ChaWMax = InclDER.setSrcRef.InclSto.setSrcRef.ChaWMax.setMag
        self.DschWMax = InclDER.setSrcRef.InclSto.setSrcRef.DschWMax.setMag
        self.ChaEfc = (
            InclDER.setSrcRef.InclSto.setSrcRef.ChaEfcPct.setMag / 100.0
            if InclDER.setSrcRef.InclSto.setSrcRef.ChaEfcPct.setMag > 0
            else 0.96
        )
        self.DschEfc = (
            InclDER.setSrcRef.InclSto.setSrcRef.DschEfcPct.setMag / 100.0
            if InclDER.setSrcRef.InclSto.setSrcRef.DschEfcPct.setMag > 0
            else 0.96
        )

        # contract parameters
        self.DcscVrblFee = InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.VrblFee.setMag
        self.DcscGridLos = InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.PctGriLos.setMag / 100.0
        self.DcscVAT = InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.VATpct.setMag / 100.0
        self.DcscCnttWatt = InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.CnttWatt.setMag
        self.DprcVrblFee = InclDER.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.VrblFee.setMag
        self.DprcVAT = InclDER.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.VATpct.setMag / 100.0
        self.DprcCnttWatt = InclDER.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.CnttWatt.setMag
        self.ActiveAlphaOneConstraintRule = ActiveAlphaOneConstraintRule

        # problem variables
        sample_rate = GnFrcst.smpRate or timedelta(minutes=15)
        self.TimeIndices: RangeSet = RangeSet(0, min(len(self.GnFrcst), len(self.DamPrcFrcst), len(self.LodFrcst)) - 1)
        self.TimeIndices2: RangeSet = RangeSet(
            0, min(len(self.GnFrcst), len(self.DamPrcFrcst), len(self.LodFrcst)) - 2
        )
        self.WtoWhConversion: float = sample_rate.total_seconds() / 3600

        self.WCharge = Var(self.TimeIndices, bounds=(self.ChaWMax, 0))
        self.WDischarge = Var(self.TimeIndices, bounds=(0, self.DschWMax))
        self.WVariationAbs = Var(self.TimeIndices2)
        self.WhStateOfEnergy = Var(
            self.TimeIndices, bounds=(self.UseWh * self.UseWhMinPct / 100, self.UseWh * self.UseWhMaxPct / 100)
        )
        self.WWithdrawn = Var(self.TimeIndices, bounds=(-self.DcscCnttWatt, 0))
        self.WFed = Var(self.TimeIndices, bounds=(0, self.DprcCnttWatt))
        self.WGrid = Var(self.TimeIndices, bounds=(-self.DcscCnttWatt, self.DprcCnttWatt))

        self.WGridDefinition = Constraint(self.TimeIndices, rule=self.WGridDefinitionRule)
        self.WGridDefinition2 = Constraint(self.TimeIndices, rule=self.WGridDefinitionRule2)
        self.WFedDefinition = Constraint(self.TimeIndices, rule=self.WFedDefinitionRule)
        self.WWithdrawnDefinition = Constraint(self.TimeIndices, rule=self.WWithdrawnDefinitionRule)
        self.WhStateOfEnergyDefinition = Constraint(self.TimeIndices, rule=self.WhStateOfEnergyDefinitionRule)
        self.WVariationAbsDefinition1 = Constraint(self.TimeIndices2, rule=self.WVariationAbsDefinitionRule1)
        self.WVariationAbsDefinition2 = Constraint(self.TimeIndices2, rule=self.WVariationAbsDefinitionRule2)
        self.AlphaOneConstraint = Constraint(self.TimeIndices, rule=self.AlphaOneConstraintRule)

        self.Objective = Objective(rule=self.SC_EARule, sense=minimize)

    @staticmethod
    def WGridDefinitionRule(m: "OptProb_SC_EA_1BESS", t):
        return m.WGrid[t] == m.GnFrcst[t] + m.LodFrcst[t] + m.WDischarge[t] + m.WCharge[t]

    @staticmethod
    def WGridDefinitionRule2(m: "OptProb_SC_EA_1BESS", t):
        return m.WGrid[t] == cast(VarData, m.WFed[t]) + m.WWithdrawn[t]

    @staticmethod
    def WFedDefinitionRule(m: "OptProb_SC_EA_1BESS", t):
        return m.WFed[t] >= m.GnFrcst[t] + m.LodFrcst[t] + m.WDischarge[t] + m.WCharge[t]

    @staticmethod
    def WWithdrawnDefinitionRule(m: "OptProb_SC_EA_1BESS", t):
        return m.WWithdrawn[t] <= m.GnFrcst[t] + m.LodFrcst[t] + m.WDischarge[t] + m.WCharge[t]

    @staticmethod
    def WhStateOfEnergyDefinitionRule(m: "OptProb_SC_EA_1BESS", t):
        if t == 0:
            return m.WhStateOfEnergy[t] == m.SocWh - cast(
                VarData,
                (cast(VarData, m.WCharge[t]) * m.ChaEfc + cast(VarData, m.WDischarge[t]) / m.DschEfc)
                * m.WtoWhConversion,
            )
        else:
            return m.WhStateOfEnergy[t] == m.WhStateOfEnergy[t - 1] - cast(
                VarData,
                (cast(VarData, m.WCharge[t]) * m.ChaEfc + cast(VarData, m.WDischarge[t]) / m.DschEfc)
                * m.WtoWhConversion,
            )

    @staticmethod
    def WVariationAbsDefinitionRule1(m: "OptProb_SC_EA_1BESS", t):
        return (
            m.WVariationAbs[t]
            >= cast(VarData, m.WDischarge[t + 1]) - m.WDischarge[t] + m.WCharge[t + 1] - m.WCharge[t]
        )

    @staticmethod
    def WVariationAbsDefinitionRule2(m: "OptProb_SC_EA_1BESS", t):
        return (
            m.WVariationAbs[t]
            >= -cast(VarData, m.WDischarge[t + 1]) + m.WDischarge[t] - m.WCharge[t + 1] + m.WCharge[t]
        )

    @staticmethod
    def SC_EARule(m: "OptProb_SC_EA_1BESS"):
        # DAM prices are provided in EUR/MWh; contract variable fees are expressed in EUR/Wh.
        return (
            -sum(
                (
                    m.WWithdrawn[t] * m.WtoWhConversion * m.DamPrcFrcst[t] * 1e-6
                    + cast(VarData, m.WWithdrawn[t]) * m.WtoWhConversion * (1 + m.DcscGridLos) * m.DcscVrblFee
                )
                * (1 + m.DcscVAT)
                for t in cast(list, m.TimeIndices)
            )
            - sum(
                cast(VarData, m.WFed[t])
                * m.WtoWhConversion
                * (m.DamPrcFrcst[t] * 1e-6 - m.DprcVrblFee)
                * (1 - m.DprcVAT)
                for t in cast(list, m.TimeIndices)
            )
            - sum(cast(VarData, m.WCharge[t]) * 1e-6 for t in cast(list, m.TimeIndices))
            + sum(cast(VarData, m.WDischarge[t]) * 1e-6 for t in cast(list, m.TimeIndices))
            + sum(cast(VarData, m.WVariationAbs[t]) * 1e-6 for t in cast(list, m.TimeIndices2))
        )

    @staticmethod
    def AlphaOneConstraintRule(m: "OptProb_SC_EA_1BESS", t):
        if m.ActiveAlphaOneConstraintRule:
            if m.GnFrcst[t] + m.LodFrcst[t] <= 0:
                return m.WCharge[t] == 0
            else:
                return m.WCharge[t] >= -(m.GnFrcst[t] + m.LodFrcst[t])
        else:
            return Constraint.Skip


class OptProb_CSC_SC_EA_mBESS(ConcreteModel):
    """Multi-user BESS optimization with CSC (Collective Self-Consumption) logic"""

    def __init__(
        self,
        users_data: dict[int, dict],
        CSC_passive_partecipants_fed: TES_2025a,
        CSC_passive_partecipants_withdrawn: TES_2025a,
        ActiveAlphaOneConstraintRule: bool = True,
        IncentivePrice: float = 0.00012,
    ):
        super().__init__()

        # Passive aggregates
        self.CSC_passive_fed = CSC_passive_partecipants_fed.val if CSC_passive_partecipants_fed.val else []
        self.CSC_passive_withdrawn = (
            CSC_passive_partecipants_withdrawn.val if CSC_passive_partecipants_withdrawn.val else []
        )

        # Determine common parameters
        sample_rate = None
        num_samples = 0
        for user_id, data in users_data.items():
            if sample_rate is None:
                sample_rate = data["LodFrcst"].smpRate or timedelta(minutes=15)
            num_samples = data["LodFrcst"].smpNum
            break

        if num_samples == 0:
            return

        self.WtoWhConversion: float = sample_rate.total_seconds() / 3600 if sample_rate else 0.25

        # Sets
        self.UserIndices: Set = Set(initialize=list(users_data.keys()))
        self.TimeIndices: RangeSet = RangeSet(0, num_samples - 1)
        self.TimeIndices2: RangeSet = RangeSet(0, num_samples - 2)

        # Store model parameters as attributes (like OptProb_SC_EA_1BESS does)
        self.ActiveAlphaOneConstraintRule = ActiveAlphaOneConstraintRule
        self.IncentivePrice = IncentivePrice

        # Prepare per-user data and store as model attributes
        for user_id, data in users_data.items():
            InclDER = data["InclDER"]
            # Forecasts
            setattr(self, f"GnFrcst_{user_id}", data["GnFrcst"].val)
            setattr(self, f"LodFrcst_{user_id}", data["LodFrcst"].val)
            setattr(self, f"DamPrcFrcst_{user_id}", data["DamPrcFrcst"].val)
            # Battery parameters
            setattr(self, f"SocWh_{user_id}", InclDER.setSrcRef.InclSto.setSrcRef.SocWh.mag)
            setattr(self, f"UseWh_{user_id}", InclDER.setSrcRef.InclSto.setSrcRef.UseWh.setMag)
            setattr(self, f"UseWhMinPct_{user_id}", InclDER.setSrcRef.InclSto.setSrcRef.UseWhMinPct.setMag)
            setattr(self, f"UseWhMaxPct_{user_id}", InclDER.setSrcRef.InclSto.setSrcRef.UseWhMaxPct.setMag)
            setattr(self, f"ChaWMax_{user_id}", InclDER.setSrcRef.InclSto.setSrcRef.ChaWMax.setMag)
            setattr(self, f"DschWMax_{user_id}", InclDER.setSrcRef.InclSto.setSrcRef.DschWMax.setMag)
            setattr(
                self,
                f"ChaEfc_{user_id}",
                (
                    InclDER.setSrcRef.InclSto.setSrcRef.ChaEfcPct.setMag / 100.0
                    if InclDER.setSrcRef.InclSto.setSrcRef.ChaEfcPct.setMag > 0
                    else 0.96
                ),
            )
            setattr(
                self,
                f"DschEfc_{user_id}",
                (
                    InclDER.setSrcRef.InclSto.setSrcRef.DschEfcPct.setMag / 100.0
                    if InclDER.setSrcRef.InclSto.setSrcRef.DschEfcPct.setMag > 0
                    else 0.96
                ),
            )
            # Contract parameters
            setattr(
                self,
                f"DcscVrblFee_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.VrblFee.setMag,
            )
            setattr(
                self,
                f"DcscGridLos_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.PctGriLos.setMag / 100.0,
            )
            setattr(
                self,
                f"DcscVAT_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.VATpct.setMag / 100.0,
            )
            setattr(
                self,
                f"DcscCnttWatt_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.CsmpCnttRef.setSrcRef.CnttWatt.setMag,
            )
            setattr(
                self,
                f"DprcVrblFee_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.VrblFee.setMag,
            )
            setattr(
                self,
                f"DprcVAT_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.VATpct.setMag / 100.0,
            )
            setattr(
                self,
                f"DprcCnttWatt_{user_id}",
                InclDER.setSrcRef.OutEcpRef.setSrcRef.PrdcCnttRef.setSrcRef.CnttWatt.setMag,
            )

        # Decision Variables indexed by [user, time]
        self.WCharge = Var(self.UserIndices, self.TimeIndices, bounds=self._WCharge_bounds)
        self.WDischarge = Var(self.UserIndices, self.TimeIndices, bounds=self._WDischarge_bounds)
        self.WhStateOfEnergy = Var(self.UserIndices, self.TimeIndices, bounds=self._WhStateOfEnergy_bounds)
        self.WWithdrawn = Var(self.UserIndices, self.TimeIndices, bounds=self._WWithdrawn_bounds)
        self.WFed = Var(self.UserIndices, self.TimeIndices, bounds=self._WFed_bounds)
        self.WGrid = Var(self.UserIndices, self.TimeIndices, bounds=self._WGrid_bounds)
        self.WVariationAbs = Var(self.UserIndices, self.TimeIndices2)

        # CSC linearization variable
        self.CSC_Volume = Var(self.TimeIndices, bounds=(0, float("inf")))

        # Constraints
        self.WGridDefinition = Constraint(self.UserIndices, self.TimeIndices, rule=self.WGridDefinitionRule)
        self.WGridDefinition2 = Constraint(self.UserIndices, self.TimeIndices, rule=self.WGridDefinitionRule2)
        self.WFedDefinition = Constraint(self.UserIndices, self.TimeIndices, rule=self.WFedDefinitionRule)
        self.WWithdrawnDefinition = Constraint(self.UserIndices, self.TimeIndices, rule=self.WWithdrawnDefinitionRule)
        self.WhStateOfEnergyDefinition = Constraint(
            self.UserIndices, self.TimeIndices, rule=self.WhStateOfEnergyDefinitionRule
        )
        self.WVariationAbsDefinition1 = Constraint(
            self.UserIndices, self.TimeIndices2, rule=self.WVariationAbsDefinitionRule1
        )
        self.WVariationAbsDefinition2 = Constraint(
            self.UserIndices, self.TimeIndices2, rule=self.WVariationAbsDefinitionRule2
        )
        self.AlphaOneConstraint = Constraint(self.UserIndices, self.TimeIndices, rule=self.AlphaOneConstraintRule)

        # CSC constraints
        self.CSCConstraint1 = Constraint(self.TimeIndices, rule=self.CSCConstraintRule1)
        self.CSCConstraint2 = Constraint(self.TimeIndices, rule=self.CSCConstraintRule2)

        # Objective
        self.Objective = Objective(rule=self.CSC_SC_EARule, sense=minimize)

    # Bounds methods
    def _WCharge_bounds(self, m, u, t):
        return (getattr(m, f"ChaWMax_{u}"), 0)

    def _WDischarge_bounds(self, m, u, t):
        return (0, getattr(m, f"DschWMax_{u}"))

    def _WhStateOfEnergy_bounds(self, m, u, t):
        UseWh = getattr(m, f"UseWh_{u}")
        UseWhMinPct = getattr(m, f"UseWhMinPct_{u}")
        UseWhMaxPct = getattr(m, f"UseWhMaxPct_{u}")
        return (UseWh * UseWhMinPct / 100, UseWh * UseWhMaxPct / 100)

    def _WWithdrawn_bounds(self, m, u, t):
        return (-getattr(m, f"DcscCnttWatt_{u}"), 0)

    def _WFed_bounds(self, m, u, t):
        return (0, getattr(m, f"DprcCnttWatt_{u}"))

    def _WGrid_bounds(self, m, u, t):
        return (-getattr(m, f"DcscCnttWatt_{u}"), getattr(m, f"DprcCnttWatt_{u}"))

    @staticmethod
    def WGridDefinitionRule(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """WGrid = Generation + Load + Discharge + Charge"""
        return (
            m.WGrid[u, t]
            == getattr(m, f"GnFrcst_{u}")[t] + getattr(m, f"LodFrcst_{u}")[t] + m.WDischarge[u, t] + m.WCharge[u, t]
        )

    @staticmethod
    def WGridDefinitionRule2(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """WGrid = WFed + WWithdrawn"""
        return m.WGrid[u, t] == cast(VarData, m.WFed[u, t]) + m.WWithdrawn[u, t]

    @staticmethod
    def WFedDefinitionRule(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """WFed >= WGrid (injection constraint)"""
        return m.WFed[u, t] >= (
            getattr(m, f"GnFrcst_{u}")[t] + getattr(m, f"LodFrcst_{u}")[t] + m.WDischarge[u, t] + m.WCharge[u, t]
        )

    @staticmethod
    def WWithdrawnDefinitionRule(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """WWithdrawn <= WGrid (withdrawal constraint)"""
        return m.WWithdrawn[u, t] <= (
            getattr(m, f"GnFrcst_{u}")[t] + getattr(m, f"LodFrcst_{u}")[t] + m.WDischarge[u, t] + m.WCharge[u, t]
        )

    @staticmethod
    def WhStateOfEnergyDefinitionRule(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """State of Energy evolution"""
        if t == 0:
            return m.WhStateOfEnergy[u, t] == getattr(m, f"SocWh_{u}") - cast(
                VarData,
                (
                    cast(VarData, m.WCharge[u, t]) * getattr(m, f"ChaEfc_{u}")
                    + cast(VarData, m.WDischarge[u, t]) / getattr(m, f"DschEfc_{u}")
                )
                * m.WtoWhConversion,
            )
        else:
            return m.WhStateOfEnergy[u, t] == m.WhStateOfEnergy[u, t - 1] - cast(
                VarData,
                (
                    cast(VarData, m.WCharge[u, t]) * getattr(m, f"ChaEfc_{u}")
                    + cast(VarData, m.WDischarge[u, t]) / getattr(m, f"DschEfc_{u}")
                )
                * m.WtoWhConversion,
            )

    @staticmethod
    def WVariationAbsDefinitionRule1(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """Absolute power variation (positive direction)"""
        return (
            m.WVariationAbs[u, t]
            >= cast(VarData, m.WDischarge[u, t + 1])
            - m.WDischarge[u, t]
            + cast(VarData, m.WCharge[u, t + 1])
            - m.WCharge[u, t]
        )

    @staticmethod
    def WVariationAbsDefinitionRule2(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """Absolute power variation (negative direction)"""
        return m.WVariationAbs[u, t] >= -(cast(VarData, m.WDischarge[u, t + 1]) - m.WDischarge[u, t]) - (
            cast(VarData, m.WCharge[u, t + 1]) - cast(VarData, m.WCharge[u, t])
        )

    @staticmethod
    def AlphaOneConstraintRule(m: "OptProb_CSC_SC_EA_mBESS", u, t):
        """Alpha=1: Battery can only charge if local surplus is positive"""
        if m.ActiveAlphaOneConstraintRule:
            local_surplus = getattr(m, f"GnFrcst_{u}")[t] + getattr(m, f"LodFrcst_{u}")[t]
            if local_surplus <= 0:
                return m.WCharge[u, t] == 0
            else:
                return m.WCharge[u, t] >= -local_surplus
        else:
            return Constraint.Skip

    @staticmethod
    def CSCConstraintRule1(m: "OptProb_CSC_SC_EA_mBESS", t):
        """CSC linearization constraint 1: CSC_Volume <= Total_Fed"""
        total_fed = cast(VarData, sum(cast(VarData, m.WFed[u, t]) for u in cast(list, m.UserIndices))) + (
            m.CSC_passive_fed[t] if t < len(m.CSC_passive_fed) else 0
        )
        return m.CSC_Volume[t] <= total_fed

    @staticmethod
    def CSCConstraintRule2(m: "OptProb_CSC_SC_EA_mBESS", t):
        """CSC linearization constraint 2: CSC_Volume <= |Total_Withdrawn|"""
        # WWithdrawn is negative, so -WWithdrawn is positive
        total_withdrawn = cast(VarData, sum(cast(VarData, m.WWithdrawn[u, t]) for u in cast(list, m.UserIndices))) + (
            m.CSC_passive_withdrawn[t] if t < len(m.CSC_passive_withdrawn) else 0
        )
        return m.CSC_Volume[t] <= -total_withdrawn

    @staticmethod
    def CSC_SC_EARule(m: "OptProb_CSC_SC_EA_mBESS"):
        """Minimize costs - maximize CSC incentive"""
        # DAM prices are provided in EUR/MWh; contract variable fees are expressed in EUR/Wh.
        # CSC incentives are expressed in EUR/Wh.
        # Costs for each user (withdrawal and fees minus injection)
        user_costs = -sum(
            (
                m.WWithdrawn[u, t] * m.WtoWhConversion * getattr(m, f"DamPrcFrcst_{u}")[t] * 1e-6
                + cast(VarData, m.WWithdrawn[u, t])
                * m.WtoWhConversion
                * (1 + getattr(m, f"DcscGridLos_{u}"))
                * getattr(m, f"DcscVrblFee_{u}")
            )
            * (1 + getattr(m, f"DcscVAT_{u}"))
            for u in cast(list, m.UserIndices)
            for t in cast(list, m.TimeIndices)
        ) - sum(
            cast(VarData, m.WFed[u, t])
            * m.WtoWhConversion
            * (getattr(m, f"DamPrcFrcst_{u}")[t] * 1e-6 - getattr(m, f"DprcVrblFee_{u}"))
            * (1 - getattr(m, f"DprcVAT_{u}"))
            for u in cast(list, m.UserIndices)
            for t in cast(list, m.TimeIndices)
        )

        # Small penalties for power variation and degradation
        # Penalise battery throughput (WCharge <= 0, WDischarge >= 0): -WCharge and +WDischarge
        # are both non-negative, so they add a small cost. Sign aligned with SC_EARule.
        degradation_cost = sum(
            -cast(VarData, m.WCharge[u, t]) * 1e-6 + cast(VarData, m.WDischarge[u, t]) * 1e-6
            for u in cast(list, m.UserIndices)
            for t in cast(list, m.TimeIndices)
        )

        variation_cost = sum(
            cast(VarData, m.WVariationAbs[u, t]) * 1e-6
            for u in cast(list, m.UserIndices)
            for t in cast(list, m.TimeIndices2)
        )

        # CSC incentive (negative because we minimize, so we subtract the incentive)
        csc_incentive = sum(
            cast(VarData, m.CSC_Volume[t]) * m.WtoWhConversion * m.IncentivePrice for t in cast(list, m.TimeIndices)
        )

        return user_costs + degradation_cost + variation_cost - csc_incentive
