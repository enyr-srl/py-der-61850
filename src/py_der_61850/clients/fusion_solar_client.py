import json
import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from py_der_61850.clients.huawei_device_client import HuaweiDeviceClient

HUAWEI_WRITE_SENT = "sent"
HUAWEI_WRITE_QUEUED = "queued"
HUAWEI_WRITE_FAILED = "failed"
HUAWEI_WRITE_SKIPPED = "skipped"


class FusionSolarAuthError(RuntimeError):
    """Raised when Huawei authentication or session recovery fails."""


@dataclass(frozen=True)
class _PendingChargeDischargeCommand:
    value: str
    control_type: int
    command_timestamp: datetime | None = None
    duplicate_retry_attempted: bool = False


class LoginPayload(BaseModel):
    userName: str
    systemCode: str


class RequestPayload(BaseModel):
    pageNo: int = 1


class StationData(BaseModel):
    model_config = {"extra": "allow"}

    capacity: float
    contactMethod: str | None = None
    contactPerson: str | None = None
    gridConnectionDate: datetime
    latitude: float
    longitude: float
    plantAddress: str
    plantCode: str
    plantName: str


class StationResponseData(BaseModel):
    items: list[StationData] = Field(alias="list")


class StationsResponse(BaseModel):
    data: StationResponseData
    failCode: int
    message: str | None
    success: bool


class DevicePayload(BaseModel):
    stationCodes: str


class DeviceData(BaseModel):
    model_config = {"extra": "allow"}

    devDn: str
    devName: str
    devTypeId: int
    esnCode: str | None = None
    id: int
    invType: str | None = None
    latitude: float
    longitude: float
    model: str | None = None
    optimizerNumber: int | None = None
    softwareVersion: str | None = None
    stationCode: str


class DevicesResponse(BaseModel):
    data: list[DeviceData]
    failCode: int
    message: str | None
    success: bool


class StationKpiPayload(BaseModel):
    stationCodes: str


class ChargeDischargeTask(BaseModel):
    plantCode: str = Field(description="The unique code identifying the plant.")
    dispatchSwitch: int = Field(
        description="1 forced charge, 2 forced discharge, 0 to stop forced charge and discharge."
    )
    controlType: int = Field(description="1 soc control, 2 duration control.")
    dispatchTime: int = Field(description="Duration in minutes for charge/discharge.")
    powerDispatch: int = Field(description="Power in Watts for charge/discharge.")


class BatteryConfigurationInfo(BaseModel):
    endOfDischargeSoc: int | None = Field(
        None, description="The state of charge (SOC) percentage at which the battery stops discharging."
    )
    endOfChargeSoc: int = Field(
        description="The state of charge (SOC) percentage at which the battery stops charging."
    )
    maximumDischargePower: int = Field(description="The maximum power in Watts that the battery can discharge.")
    maximumChargePower: int = Field(description="The maximum power in Watts that the battery can charge.")


class SettingsParamsTask(BaseModel):
    plantCode: str
    batteryConfigurationInfo: BatteryConfigurationInfo


class ControlInverterActivePowerInfo(BaseModel):
    maxGridFeedInPower: int = Field(description="Maximum grid feed-in power (kW).")


class InverterActivePowerTask(BaseModel):
    plantCode: str
    controlInfo: ControlInverterActivePowerInfo


class StationKpiData(BaseModel):
    model_config = {"extra": "allow"}

    total_income: float | None = Field(
        default=None, description="Total revenue. Currency specified in the management system. Updated every 1 hour."
    )
    total_power: float | None = Field(
        default=None,
        description="Total yield in kWh. Statistics collected from device connection to management system. Updated every 5 minutes.",
    )
    day_on_grid_energy: float | None = Field(
        default=None, description="Daily on-grid energy in kWh. Updated every 5 minutes."
    )
    day_power: float | None = Field(
        default=None, description="Energy yield of current day in kWh. Updated every 5 minutes."
    )
    day_use_energy: float | None = Field(
        default=None, description="Consumption today in kWh. Updated every 5 minutes."
    )
    day_income: float | None = Field(
        default=None,
        description="Revenue today. Currency specified in the management system. Updated every 5 minutes.",
    )
    real_health_state: int | None = Field(
        default=None, description="Plant health status: 1=disconnected, 2=faulty, 3=healthy. Updated every 5 minutes."
    )
    month_power: float | None = Field(default=None, description="Yield this month in kWh. Updated every 5 minutes.")


class DeviceKpiPayload(BaseModel):
    devIds: str
    sns: str | None = None
    devTypeId: int = Field(
        description="""Device type ID. The values of devTypeId obtained in Device List API are used.
            The following device types are supported:
                1: string inverter
                10: EMI
                17: grid meter
                38: residential inverter
                39: battery
                41: ESS
                47: power sensor
                60001: mains
                60003: genset
                60043: SSU group
                60044: SSU
                60092: power converter
                60014: lithium battery rack
                60010: AC output power distribution
                23070: EMMA)
                """
    )


class DeviceKpiData(BaseModel):
    model_config = {"extra": "allow"}
    devId: int
    sn: str | None
    dataItemMap: dict[str, Any]


class FusionSolarClient(HuaweiDeviceClient):
    def __init__(
        self,
        base_url: str,
        plant_code: str,
        oauth_base_url: str,
        username: str,
        password: str,
        refresh_token: str,
        token_cache_path: str = ".fusion_solar_token_cache.json",
        debug: bool = False,
        device_fallback: list[dict] | None = None,
    ):
        self.username = username
        self.password = password
        self.refresh_token = refresh_token
        self.base_url = base_url
        self.oauth_base_url = oauth_base_url
        self.client = httpx.Client(verify=True, timeout=20.0)
        self.default_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        self.token_cache_path = Path(token_cache_path)
        self._rate_limit_window_seconds = 14 * 60
        self._rate_limit_max_calls = 5
        self._call_history: dict[str, Any] = {}
        self.debug = debug
        self._device_fallback = device_fallback or []
        self.plant_device_data: dict = {}
        self.plant_code = plant_code
        self._charge_discharge_guard_seconds = 30
        self._charge_discharge_duplicate_retry_seconds = 10
        self._charge_discharge_busy_until: datetime | None = None
        self._charge_discharge_pending_command: _PendingChargeDischargeCommand | None = None
        self._charge_discharge_retry_timer: threading.Timer | None = None
        self._charge_discharge_inflight = False
        self._charge_discharge_last_task: dict[str, Any] | None = None
        self._charge_discharge_lock = threading.RLock()

        xsrf_token = self.get_xsrf_token(payload=LoginPayload(userName=self.username, systemCode=self.password))

        # Before splitting a docker for cloud-edge we need to fetch all stations and plants to get all plant_codes and related device ids.
        # self.plants = self.get_stations(xsrf_token, RequestPayload())
        # plant_codes = [plant.plantCode for plant in self.plants]
        # self.devices = self.get_devices(xsrf_token, DevicePayload(stationCodes=",".join(plant_codes)))

        # Now we can get just the plant_code related devices having a docker for each plant.
        self.devices = self._get_devices_with_fallback(xsrf_token, plant_code)

    def _get_devices_with_fallback(self, xsrf_token: str | None, plant_code: str) -> list[DeviceData]:
        """Fetch the device list, tolerating a failing ``getDevList`` via a configured fallback.

        ``getDevList`` (``/thirdData/getDevList``) is a one-time startup discovery call used only
        to learn the devices of the plant. Huawei can throttle/block it for a single station
        (observed ``failCode=20056`` on one plant after intensive calls) even while the per-device
        read/control interfaces keep working and the device IDs are already known from config.
        Without this fallback, that one failing call makes the whole edge fail to start -> no reads
        AND no control. When a ``device_fallback`` is configured, use it instead of crashing so the
        edge keeps operating with the known device IDs; reads use ``get_device_kpi`` (different
        interface). The fallback is used ONLY when the live call fails AND a fallback is provided;
        otherwise the original error propagates unchanged (no silent masking).
        """
        try:
            return self.get_devices(xsrf_token, DevicePayload(stationCodes=plant_code))
        except Exception as exc:
            if not self._device_fallback:
                raise
            devices = [DeviceData.model_validate(d) for d in self._device_fallback]
            logger.warning(
                "[HUAWEI READ] getDevList failed for plant {} ({}: {}); using configured device "
                "fallback ({} devices). Reads/control continue with known device IDs.",
                plant_code,
                type(exc).__name__,
                exc,
                len(devices),
            )
            return devices

    def _save_response(self, path: Path, response_json: dict) -> None:
        """Save a response envelope with saved_at."""
        envelope = {
            "saved_at": int(time.time()),
            "response": response_json,
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_response(self, path: Path) -> dict | None:
        """Load cached response envelope and return the inner response dict."""
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(cached, dict):
            return None

        saved_at = cached.get("saved_at")
        resp = cached.get("response")
        if not isinstance(saved_at, int) or not isinstance(resp, dict):
            return None
        if time.time() - saved_at > self._rate_limit_window_seconds:
            return None
        return resp

    def read(self, address: str, type: str, function: str, devId: int, multiplier: float) -> Any:
        method: Callable = getattr(self, function)
        xsrf_token = self.get_xsrf_token(payload=LoginPayload(userName=self.username, systemCode=self.password))

        for device in self.devices:
            if device.id == devId:
                dev_type_id = device.devTypeId

                dev_ids = [device.id for device in self.devices if device.devTypeId == dev_type_id]

                ts = datetime.now()
                if dev_type_id not in self.plant_device_data or ts - self.plant_device_data[dev_type_id][
                    "ts"
                ] > timedelta(seconds=self._rate_limit_window_seconds):
                    dev_kpi_ids = ",".join(str(id) for id in dev_ids)
                    results = method(xsrf_token, DeviceKpiPayload(devIds=dev_kpi_ids, devTypeId=dev_type_id))
                    if not results:
                        logger.warning(f"No KPI data returned for device type {dev_type_id} with IDs {dev_ids}")
                    else:
                        self.plant_device_data[dev_type_id] = {"dev_kpi_ids": dev_ids, "ts": ts, "values": results}

                for kpi in self.plant_device_data[dev_type_id]["values"]:
                    if kpi.devId == device.id:
                        paths = address.split(".")
                        for path in paths:
                            if isinstance(kpi, dict):
                                kpi = kpi.get(path)
                            else:
                                kpi = getattr(kpi, path)
                        if kpi is None:
                            logger.warning(f"KPI path '{address}' not found for device ID {device.id}")
                            return "0"

                        kpi = kpi * multiplier
                        if type == "int" and isinstance(kpi, float):
                            kpi = int(round(kpi, 0))

                        logger.warning(f"[HUAWEI READ FUNCTION] Address: '{address}' value={kpi}")
                        return kpi

        raise ValueError(f"Device with id {devId} not found.")

    def _ensure_charge_discharge_queue_state(self) -> None:
        if not hasattr(self, "_charge_discharge_lock"):
            self._charge_discharge_lock = threading.RLock()
        if not hasattr(self, "_charge_discharge_guard_seconds"):
            self._charge_discharge_guard_seconds = 30
        if not hasattr(self, "_charge_discharge_duplicate_retry_seconds"):
            self._charge_discharge_duplicate_retry_seconds = 10
        if not hasattr(self, "_charge_discharge_busy_until"):
            self._charge_discharge_busy_until = None
        if not hasattr(self, "_charge_discharge_pending_command"):
            self._charge_discharge_pending_command = None
        if not hasattr(self, "_charge_discharge_retry_timer"):
            self._charge_discharge_retry_timer = None
        if not hasattr(self, "_charge_discharge_inflight"):
            self._charge_discharge_inflight = False
        if not hasattr(self, "_charge_discharge_last_task"):
            self._charge_discharge_last_task = None

    @staticmethod
    def _seconds_since_quarter(now: datetime) -> float:
        return (now.minute % 15) * 60 + now.second + now.microsecond / 1_000_000

    @classmethod
    def _dispatch_time_for_now(cls, now: datetime) -> int | None:
        seconds_since_quarter = cls._seconds_since_quarter(now)
        quarter_seconds = 15 * 60
        if seconds_since_quarter <= 30 or seconds_since_quarter >= quarter_seconds - 30:
            return 15

        dispatch_time = int((quarter_seconds - seconds_since_quarter) // 60)
        return dispatch_time if dispatch_time >= 1 else None

    @staticmethod
    def _command_timestamp_sort_key(timestamp: datetime | None) -> datetime | None:
        if timestamp is None:
            return None
        if timestamp.tzinfo is None:
            return timestamp
        return timestamp.astimezone(timezone.utc).replace(tzinfo=None)

    def _queue_charge_discharge_command_locked(
        self,
        command: _PendingChargeDischargeCommand,
        *,
        reason: str,
    ) -> None:
        pending = self._charge_discharge_pending_command
        if pending is not None:
            incoming_ts = self._command_timestamp_sort_key(command.command_timestamp)
            pending_ts = self._command_timestamp_sort_key(pending.command_timestamp)
            if incoming_ts is not None and pending_ts is not None and incoming_ts <= pending_ts:
                logger.info(
                    "[HUAWEI OA2 WRITE] Keeping pending command because incoming command is not newer: "
                    "incoming_ts={}, pending_ts={}",
                    command.command_timestamp.isoformat() if command.command_timestamp else None,
                    pending.command_timestamp.isoformat() if pending.command_timestamp else None,
                )
                return

        self._charge_discharge_pending_command = command
        logger.info(
            "[HUAWEI OA2 WRITE] Queued charge/discharge command: reason={}, value={}, "
            "control_type={}, command_timestamp={}",
            reason,
            command.value,
            command.control_type,
            command.command_timestamp.isoformat() if command.command_timestamp else None,
        )

    def _schedule_charge_discharge_retry_locked(self, *, delay_seconds: float, reason: str) -> None:
        delay_seconds = max(0.0, delay_seconds)
        existing_timer = self._charge_discharge_retry_timer
        if existing_timer is not None:
            existing_timer.cancel()

        timer = threading.Timer(delay_seconds, self._flush_pending_charge_discharge_command)
        timer.daemon = True
        self._charge_discharge_retry_timer = timer
        timer.start()
        logger.info(
            "[HUAWEI OA2 WRITE] Scheduled pending command flush in {:.3f}s: reason={}",
            delay_seconds,
            reason,
        )

    def _flush_pending_charge_discharge_command(self) -> None:
        self._ensure_charge_discharge_queue_state()
        with self._charge_discharge_lock:
            self._charge_discharge_retry_timer = None
            command = self._charge_discharge_pending_command
            self._charge_discharge_pending_command = None

        if command is None:
            return

        logger.info(
            "[HUAWEI OA2 WRITE] Flushing pending charge/discharge command: value={}, "
            "control_type={}, command_timestamp={}",
            command.value,
            command.control_type,
            command.command_timestamp.isoformat() if command.command_timestamp else None,
        )
        try:
            self.write(
                command.value,
                control_type=command.control_type,
                command_timestamp=command.command_timestamp,
                _from_queue=True,
                _duplicate_retry_attempted=command.duplicate_retry_attempted,
            )
        except Exception as exc:
            logger.exception(
                "[HUAWEI OA2 WRITE] Pending charge/discharge flush failed with {}; "
                "dropping command until a newer valid command arrives.",
                type(exc).__name__,
            )

    @staticmethod
    def _is_charge_discharge_accepted(response_json: dict[str, Any]) -> bool:
        if response_json.get("success") is not True or response_json.get("failCode") != 0:
            return False
        data = response_json.get("data")
        if not isinstance(data, dict):
            return False
        result = data.get("result")
        if not isinstance(result, list):
            return False
        return any(isinstance(item, dict) and item.get("dispatchResult") == 0 for item in result)

    @staticmethod
    def _is_charge_discharge_duplicate(response_json: dict[str, Any]) -> bool:
        message = str(response_json.get("message") or "").lower()
        data = response_json.get("data") if isinstance(response_json.get("data"), dict) else {}
        result = data.get("result") if isinstance(data, dict) else []
        descriptions = (
            [str(item.get("description") or "").lower() for item in result if isinstance(item, dict)]
            if isinstance(result, list)
            else []
        )
        # NB: failCode==2 e' un codice generico Huawei restituito anche per errori NON
        # ritentabili (es. "Exist no permission plants"): classificarlo come duplicato fa
        # ritentare all'infinito un permission-error, bruciando la quota della control API
        # (100 chiamate/giorno -> failCode 407, vedi prod PODXX3 16/06/2026). Riconosci il
        # duplicato SOLO dal messaggio esplicito di Huawei.
        return "duplicate task is running" in message or any(
            "duplicate task is running" in description for description in descriptions
        )

    @staticmethod
    def _accepted_charge_discharge_result(response_json: dict[str, Any]) -> dict[str, Any] | None:
        data = response_json.get("data")
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, list):
            return None
        for item in result:
            if isinstance(item, dict) and item.get("dispatchResult") == 0:
                return item
        return None

    def _post_charge_discharge_command(
        self,
        command: _PendingChargeDischargeCommand,
        *,
        dispatch_time: int,
        power: int,
        dispatch_switch: int,
        _retry: int,
    ) -> dict[str, Any]:
        access_token = self.refresh_access_token(refresh_token=self.refresh_token)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        resp = self.client.post(
            f"{self.base_url}/rest/openapi/pvms/nbi/v2/control/charge-and-discharge/async-task",
            json={
                "tasks": [
                    {
                        "plantCode": self.plant_code,
                        "dispatchSwitch": dispatch_switch,
                        "controlType": command.control_type,
                        "dispatchTime": dispatch_time,
                        "powerDispatch": power,
                    }
                ]
            },
            headers=headers,
        )
        if resp.status_code == 401 or resp.status_code == 403:
            if _retry > 0:
                logger.warning("[HUAWEI OA2 WRITE] Token expired mid-call, retrying...")
                return self._post_charge_discharge_command(
                    command,
                    dispatch_time=dispatch_time,
                    power=power,
                    dispatch_switch=dispatch_switch,
                    _retry=_retry - 1,
                )
            raise FusionSolarAuthError("[HUAWEI OA2 WRITE] Auth failed after retry.")

        resp.raise_for_status()
        response_json = resp.json()
        if self._is_auth_failure_response(response_json):
            if _retry > 0:
                logger.warning("[HUAWEI OA2 WRITE] Huawei returned auth failure payload, retrying...")
                return self._post_charge_discharge_command(
                    command,
                    dispatch_time=dispatch_time,
                    power=power,
                    dispatch_switch=dispatch_switch,
                    _retry=_retry - 1,
                )
            raise FusionSolarAuthError(
                "[HUAWEI OA2 WRITE] Auth failed after retry: "
                f"failCode={response_json.get('failCode')} message={response_json.get('message')}"
            )

        return response_json

    def write(
        self,
        value: str,
        control_type: int,
        command_timestamp: datetime | None = None,
        _retry: int = 0,
        _from_queue: bool = False,
        _duplicate_retry_attempted: bool = False,
    ) -> str:
        self._ensure_charge_discharge_queue_state()
        command = _PendingChargeDischargeCommand(
            value=value,
            control_type=control_type,
            command_timestamp=command_timestamp,
            duplicate_retry_attempted=_duplicate_retry_attempted,
        )

        now = datetime.now()
        with self._charge_discharge_lock:
            busy_until = self._charge_discharge_busy_until
            if self._charge_discharge_inflight or (busy_until is not None and now < busy_until):
                reason = "inflight" if self._charge_discharge_inflight else "busy_until"
                self._queue_charge_discharge_command_locked(command, reason=reason)
                if busy_until is not None and now < busy_until:
                    delay_seconds = (busy_until - now).total_seconds()
                    self._schedule_charge_discharge_retry_locked(
                        delay_seconds=delay_seconds,
                        reason="estimated_previous_task_end",
                    )
                return HUAWEI_WRITE_QUEUED

            dispatch_time = self._dispatch_time_for_now(now)
            if dispatch_time is None:
                logger.warning(
                    "[HUAWEI OA2 WRITE] Skipping charge/discharge command because the remaining "
                    "dispatch window is too short: value={}, control_type={}, command_timestamp={}, "
                    "from_queue={}, drift_seconds={:.3f}",
                    value,
                    control_type,
                    command_timestamp.isoformat() if command_timestamp else None,
                    _from_queue,
                    self._seconds_since_quarter(now),
                )
                return HUAWEI_WRITE_SKIPPED

            self._charge_discharge_inflight = True

        # IEC61850: value > 0 -> DISCHARGE, value < 0 -> CHARGE
        # HUAWEI: value > 0 -> CHARGE, value < 0 -> DISCHARGE
        power_float = -float(value)
        if power_float > 0:
            dispatch_switch = 1  # forced charge
        elif power_float < 0:
            dispatch_switch = 2  # forced discharge
        else:
            dispatch_switch = 1  # forced charge
            power_float = 1
            logger.warning(
                "[HUAWEI OA2 WRITE] IEC setpoint is 0.0; "
                "sending forced charge at 1 W because Huawei control does not accept zero."
            )
        power = int(power_float)

        logger.info(
            "[HUAWEI OA2 WRITE] Delivering charge/discharge command: value={}, "
            "control_type={}, dispatchSwitch={}, dispatchTime={}, powerDispatch={}, "
            "command_timestamp={}, from_queue={}, drift_seconds={:.3f}",
            value,
            control_type,
            dispatch_switch,
            dispatch_time,
            power,
            command_timestamp.isoformat() if command_timestamp else None,
            _from_queue,
            self._seconds_since_quarter(now),
        )

        try:
            huawei_async_task = self._post_charge_discharge_command(
                command,
                dispatch_time=dispatch_time,
                power=power,
                dispatch_switch=dispatch_switch,
                _retry=_retry,
            )
        except FusionSolarAuthError as exc:
            logger.warning(
                "[HUAWEI OA2 WRITE] Huawei auth/session unavailable; dropping command until a newer "
                "valid command arrives: {}",
                exc,
            )
            return HUAWEI_WRITE_FAILED
        except Exception as exc:
            logger.exception(
                "[HUAWEI OA2 WRITE] Huawei charge/discharge delivery raised {}; dropping command "
                "until a newer valid command arrives.",
                type(exc).__name__,
            )
            return HUAWEI_WRITE_FAILED
        finally:
            with self._charge_discharge_lock:
                self._charge_discharge_inflight = False

        logger.debug(f"[HUAWEI OA2 WRITE] Charge/Discharge response: {huawei_async_task}")

        accepted_at = datetime.now()
        with self._charge_discharge_lock:
            if self._is_charge_discharge_accepted(huawei_async_task):
                data = huawei_async_task.get("data") if isinstance(huawei_async_task.get("data"), dict) else {}
                accepted_result = self._accepted_charge_discharge_result(huawei_async_task) or {}
                busy_until = accepted_at + timedelta(
                    minutes=dispatch_time,
                    seconds=self._charge_discharge_guard_seconds,
                )
                self._charge_discharge_busy_until = busy_until
                self._charge_discharge_last_task = {
                    "requestID": data.get("requestID") if isinstance(data, dict) else None,
                    "subTaskId": accepted_result.get("subTaskId"),
                    "dispatchTime": dispatch_time,
                    "accepted_at": accepted_at,
                    "busy_until": busy_until,
                    "command_timestamp": command_timestamp,
                }
                logger.info(
                    "[HUAWEI OA2 WRITE] Charge/discharge accepted: requestID={}, subTaskId={}, "
                    "dispatchTime={}, accepted_at={}, busy_until={}",
                    self._charge_discharge_last_task["requestID"],
                    self._charge_discharge_last_task["subTaskId"],
                    dispatch_time,
                    accepted_at.isoformat(),
                    busy_until.isoformat(),
                )
                if self._charge_discharge_pending_command is not None:
                    self._schedule_charge_discharge_retry_locked(
                        delay_seconds=(busy_until - datetime.now()).total_seconds(),
                        reason="pending_after_accepted_task",
                    )
                return HUAWEI_WRITE_SENT

            if self._is_charge_discharge_duplicate(huawei_async_task):
                if command.duplicate_retry_attempted:
                    logger.warning(
                        "[HUAWEI OA2 WRITE] Huawei still reports duplicate/running task after the "
                        "single allowed retry; dropping command until a newer valid command arrives."
                    )
                    return HUAWEI_WRITE_FAILED
                self._queue_charge_discharge_command_locked(
                    replace(command, duplicate_retry_attempted=True),
                    reason="huawei_duplicate_task_running",
                )
                self._schedule_charge_discharge_retry_locked(
                    delay_seconds=self._charge_discharge_duplicate_retry_seconds,
                    reason="huawei_duplicate_task_running",
                )
                logger.warning(
                    "[HUAWEI OA2 WRITE] Huawei reports duplicate/running task; queued one retry in {}s",
                    self._charge_discharge_duplicate_retry_seconds,
                )
                return HUAWEI_WRITE_QUEUED

        logger.error("[HUAWEI OA2 WRITE] Charge/discharge delivery failed: {}", huawei_async_task)
        return HUAWEI_WRITE_FAILED

    def _login_payload(self) -> LoginPayload:
        return LoginPayload(userName=self.username, systemCode=self.password)

    def _clear_xsrf_session_state(self) -> None:
        try:
            self.token_cache_path.unlink()
        except FileNotFoundError:
            pass
        self.client.cookies.clear()

    def _extract_xsrf_token(self, response: httpx.Response) -> str | None:
        token = response.headers.get("xsrf-token")
        if token:
            return token
        token = response.cookies.get("XSRF-TOKEN")
        if token:
            return token
        token = self.client.cookies.get("XSRF-TOKEN")
        return token if token else None

    @staticmethod
    def _is_auth_failure_response(response_json: dict[str, Any]) -> bool:
        message = str(response_json.get("message") or "").upper()
        return response_json.get("failCode") == 305 or "INVALID_CREDENTIAL" in message

    def _login_for_xsrf_token(self, payload: LoginPayload) -> str | None:
        self._enforce_rate_limit(payload.userName)
        response = self.client.post(
            f"{self.base_url}/thirdData/login",
            json=payload.model_dump(),
            headers=self.default_headers,
            follow_redirects=False,
        )
        response.raise_for_status()
        token = self._extract_xsrf_token(response)
        if token:
            self._save_token(payload.userName, token)
            return token

        response_json: dict[str, Any] | None = None
        try:
            parsed = response.json()
            response_json = parsed if isinstance(parsed, dict) else None
        except ValueError:
            response_json = None

        logger.warning(
            "[HUAWEI READ AUTH] Login response missing XSRF token: status={} failCode={} message={}",
            response.status_code,
            response_json.get("failCode") if response_json is not None else None,
            response_json.get("message") if response_json is not None else None,
        )
        return None

    def get_xsrf_token(self, payload: LoginPayload, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = self._load_cached_token(payload.userName)
            if cached is not None:
                return cached

        last_exc: Exception | None = None
        for attempt in range(2):
            if force_refresh or attempt > 0:
                self._clear_xsrf_session_state()
            try:
                token = self._login_for_xsrf_token(payload)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[HUAWEI READ AUTH] Login attempt {} failed: {}",
                    attempt + 1,
                    exc,
                )
                continue
            if token:
                return token

        message = f"Huawei login did not return a valid XSRF token for account '{payload.userName}'."
        if last_exc is not None:
            raise FusionSolarAuthError(message) from last_exc
        raise FusionSolarAuthError(message)

    def _post_third_data_with_auth_retry(
        self,
        url: str,
        payload: BaseModel,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        access_token_override = access_token if access_token else None
        last_auth_error: FusionSolarAuthError | None = None

        for attempt in range(2):
            token = access_token_override
            if token is None:
                token = self.get_xsrf_token(self._login_payload(), force_refresh=attempt > 0)
            if not token:
                raise FusionSolarAuthError("Huawei XSRF token is missing before thirdData request.")

            headers = self.default_headers.copy()
            headers["XSRF-TOKEN"] = token
            response = self.client.post(url, json=payload.model_dump(), headers=headers)

            if response.status_code in {401, 403}:
                last_auth_error = FusionSolarAuthError(
                    f"Huawei thirdData auth failed with HTTP {response.status_code}."
                )
                logger.warning("[HUAWEI READ AUTH] thirdData request rejected with HTTP {}.", response.status_code)
                self._clear_xsrf_session_state()
                access_token_override = None
                if attempt == 0:
                    continue
                raise last_auth_error

            response.raise_for_status()
            response_json = response.json()
            if not isinstance(response_json, dict):
                raise RuntimeError(f"Unexpected thirdData response format: {response_json}")

            if self._is_auth_failure_response(response_json):
                last_auth_error = FusionSolarAuthError(
                    "Huawei thirdData auth failed: "
                    f"failCode={response_json.get('failCode')} message={response_json.get('message')}"
                )
                logger.warning(
                    "[HUAWEI READ AUTH] thirdData auth failure payload received: failCode={} message={}",
                    response_json.get("failCode"),
                    response_json.get("message"),
                )
                self._clear_xsrf_session_state()
                access_token_override = None
                if attempt == 0:
                    continue
                raise last_auth_error

            return response_json

        raise last_auth_error or FusionSolarAuthError("Huawei thirdData auth recovery failed.")

    def refresh_access_token(self, refresh_token: str) -> str:
        response = self.client.post(
            f"{self.oauth_base_url}/oauth2/auth/huawei/refresh", json={"refresh_token": refresh_token}
        )
        response.raise_for_status()
        response = response.json()
        return response["access_token"]

    def _base_set_control_request(self, access_token: str, url: str, tasks: Sequence[BaseModel]) -> dict:
        headers = self.default_headers.copy()
        headers["Authorization"] = f"Bearer {access_token}"
        payload = {"tasks": [task.model_dump() for task in tasks]}
        response = self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    def set_charge_discharge(self, access_token: str, tasks: Sequence[ChargeDischargeTask]) -> dict:
        url = f"{self.base_url}/rest/openapi/pvms/nbi/v2/control/charge-and-discharge/async-task"
        return self._base_set_control_request(access_token, url, tasks)

    def set_settings_params(self, access_token: str, tasks: Sequence[SettingsParamsTask]) -> dict:
        url = f"{self.base_url}/rest/openapi/pvms/nbi/v1/control/battery/configuration/async-task"
        return self._base_set_control_request(access_token, url, tasks)

    def set_inverter_active_power(self, access_token: str, tasks: Sequence[InverterActivePowerTask]) -> dict:
        url = f"{self.base_url}/rest/openapi/pvms/nbi/v2/control/active-power-control/async-task"
        return self._base_set_control_request(access_token, url, tasks)

    def _base_get_control_status(self, access_token: str, url: str, payload: dict) -> dict:
        headers = self.default_headers.copy()
        headers["Authorization"] = f"Bearer {access_token}"
        response = self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    def get_charge_discharge_status(self, access_token: str, request_id: int) -> dict:
        url = f"{self.base_url}/rest/openapi/pvms/v1/vpp/chargeAndDischargeStatus"
        payload = {"requestID": request_id}
        return self._base_get_control_status(access_token, url, payload)

    def get_settings_params_status(self, access_token: str, task_id: int) -> dict:
        url = f"{self.base_url}/rest/openapi/pvms/nbi/v1/control/battery/configuration/task-info"
        payload = {"taskId": task_id}
        return self._base_get_control_status(access_token, url, payload)

    def get_inverter_active_power_status(self, access_token: str, task_id: int) -> dict:
        url = f"{self.base_url}/rest/openapi/pvms/nbi/v2/control/active-power-control/task-info"
        payload = {"taskId": task_id}
        return self._base_get_control_status(access_token, url, payload)

    def _enforce_rate_limit(self, account_key: str) -> None:
        now = time.time()
        window_start = now - self._rate_limit_window_seconds
        history = self._call_history.get(account_key, None)
        if history is None:
            history = deque()
            self._call_history[account_key] = history
        while history and history[0] < window_start:
            history.popleft()
        if len(history) >= self._rate_limit_max_calls:
            logger.warning(
                "Rate limit exceeded (max {} calls every {}s) for account '{}'. " "Continuing without raising.",
                self._rate_limit_max_calls,
                self._rate_limit_window_seconds,
                account_key,
            )
            raise RuntimeError("Rate limit exceeded: max 5 calls every 10 minutes per account.")
        history.append(now)

    def _save_token(self, account_key: str, token: str) -> None:
        payload = {
            "account": account_key,
            "token": token,
            "saved_at": int(time.time()),
        }
        self.token_cache_path.write_text(json.dumps(payload), encoding="utf-8")

    def _load_cached_token(self, account_key: str) -> str | None:
        if not self.token_cache_path.exists():
            return None
        try:
            cached = json.loads(self.token_cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if cached.get("account") != account_key:
            return None
        saved_at = cached.get("saved_at")
        token = cached.get("token")
        if not isinstance(saved_at, int) or not isinstance(token, str):
            return None
        if time.time() - saved_at > self._rate_limit_window_seconds:
            return None
        return token

    def get_stations(self, access_token: str | None, payload: RequestPayload) -> list[StationData]:
        cache_file = Path(".get_stations.json")

        if self.debug:
            cached = self._load_response(cache_file)
            if cached is not None:
                stations = StationsResponse.model_validate(cached)
                return stations.data.items

        url = f"{self.base_url}/thirdData/stations"
        response_json = self._post_third_data_with_auth_retry(url, payload, access_token=access_token)

        if self.debug:
            self._save_response(cache_file, response_json)

        stations = StationsResponse.model_validate(response_json)
        return stations.data.items

    def get_devices(self, access_token: str | None, payload: DevicePayload) -> list[DeviceData]:
        cache_file = Path(".get_devices.json")

        if self.debug:
            cached = self._load_response(cache_file)
            if cached is not None:
                devices = DevicesResponse.model_validate(cached)
                return devices.data

        url = f"{self.base_url}/thirdData/getDevList"
        response_json = self._post_third_data_with_auth_retry(url, payload, access_token=access_token)

        if self.debug:
            self._save_response(cache_file, response_json)

        devices = DevicesResponse.model_validate(response_json)
        return devices.data

    def get_station_kpi(self, access_token: str | None, payload: StationKpiPayload) -> StationKpiData:
        url = f"{self.base_url}/thirdData/getStationRealKpi"
        response_json = self._post_third_data_with_auth_retry(url, payload, access_token=access_token)
        kpi = StationKpiData.model_validate(response_json["data"][0]["dataItemMap"])
        return kpi

    def get_device_kpi(self, access_token: str | None, payload: DeviceKpiPayload) -> list[DeviceKpiData]:
        cache_file = Path(f".get_device_kpi_{payload.devTypeId}.json")
        if self.debug:
            cached = self._load_response(cache_file)
            if cached is not None:
                return [DeviceKpiData.model_validate(item) for item in cached["data"]]
        url = f"{self.base_url}/thirdData/getDevRealKpi"
        response_json = self._post_third_data_with_auth_retry(url, payload, access_token=access_token)

        if self.debug:
            self._save_response(cache_file, response_json)

        if "data" not in response_json or not isinstance(response_json["data"], list):
            logger.warning(f"Unexpected device KPI response format: {response_json}")
            return []

        return [DeviceKpiData.model_validate(item) for item in response_json["data"]]
