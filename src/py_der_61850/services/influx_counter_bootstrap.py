import logging
from datetime import datetime
from typing import Any

from loguru import logger as loguru_logger
from py_der_61850.clients.influxdb_client import InfluxClient
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.data_objects.BCR_2025a import BCR_2025a
from py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a import MMTN_2025a
from py_der_61850.models.image_process import ImageProcess
from py_der_61850.reflection.reflection_service import ReflectionService

logger = logging.getLogger(__name__)

INFLUX_BOOTSTRAP_MODE = "influx"
_BOOTSTRAP_DONE_ATTR = "_influx_bootstrap_done"


def bootstrap_influx_counters_once(
    *,
    image_process: ImageProcess,
    reflection_service: ReflectionService,
    influx_client: InfluxClient,
    bucket: str,
    measurement: str,
) -> bool:
    if getattr(image_process, _BOOTSTRAP_DONE_ATTR, False):
        return False

    setattr(image_process, _BOOTSTRAP_DONE_ATTR, True)

    configured_bootstrap_ids = [
        attribute_id
        for attribute_id, data_attribute in image_process.data_attributes.items()
        if data_attribute.bootstrap == INFLUX_BOOTSTRAP_MODE
    ]
    if not configured_bootstrap_ids:
        return False

    for total_attribute_id in configured_bootstrap_ids:
        try:
            _bootstrap_total_counter(
                image_process=image_process,
                reflection_service=reflection_service,
                influx_client=influx_client,
                bucket=bucket,
                measurement=measurement,
                total_attribute_id=total_attribute_id,
            )
        except Exception:
            _emit_exception("Failed to bootstrap %s from Influx history.", total_attribute_id)

    return True


def _bootstrap_total_counter(
    *,
    image_process: ImageProcess,
    reflection_service: ReflectionService,
    influx_client: InfluxClient,
    bucket: str,
    measurement: str,
    total_attribute_id: str,
) -> None:
    ln_instance, total_name, da_name = total_attribute_id.rsplit(".", 2)
    if da_name != "actVal":
        _emit_warning(
            "Skipping Influx bootstrap for %s: only actVal counters are supported.",
            total_attribute_id,
        )
        return

    daily_name = _paired_daily_name(total_name)
    if daily_name is None:
        _emit_warning(
            "Skipping Influx bootstrap for %s: only SupWh/DmdWh totals are supported.",
            total_attribute_id,
        )
        return

    daily_attribute_id = f"{ln_instance}.{daily_name}.actVal"
    daily_attribute = image_process.data_attributes.get(daily_attribute_id)
    if daily_attribute is None:
        _emit_warning(
            "Skipping Influx bootstrap for %s: paired daily %s is not configured.",
            total_attribute_id,
            daily_attribute_id,
        )
        return
    total_sample = _get_last_preferred_good(
        influx_client=influx_client,
        bucket=bucket,
        measurement=measurement,
        field=total_attribute_id,
    )
    if total_sample is None:
        _emit_warning(
            "Skipping Influx bootstrap for %s: no historical total found in Influx.",
            total_attribute_id,
        )
        return

    mmtn = reflection_service.get_value(ln_instance)
    if not isinstance(mmtn, MMTN_2025a):
        _emit_warning(
            "Skipping Influx bootstrap for %s: %s is not an MMTN_2025a node.",
            total_attribute_id,
            ln_instance,
        )
        return

    current_daily = reflection_service.get_value(f"{ln_instance}.{daily_name}")
    if not isinstance(current_daily, BCR_2025a):
        _emit_warning(
            "Skipping Influx bootstrap for %s: current daily %s is not available in reflection context.",
            total_attribute_id,
            daily_name,
        )
        return

    total_value = _normalize_counter_value(total_sample.get("value"), total_attribute_id)
    total_timestamp = _normalize_timestamp(total_sample.get("Datetime"), total_attribute_id)

    daily_sample = None
    if daily_attribute.store:
        daily_sample = _get_last_preferred_good(
            influx_client=influx_client,
            bucket=bucket,
            measurement=measurement,
            field=daily_attribute_id,
            at_or_before=total_timestamp,
        )

    if daily_sample is not None:
        previous_daily_value = _normalize_counter_value(daily_sample.get("value"), daily_attribute_id)
        mark_questionable = _requires_best_effort_recovery(previous_daily_value, current_daily)
    else:
        previous_daily_value = _fallback_daily_cache_value(current_daily)
        mark_questionable = False

    mmtn.bootstrap_total_from_history(
        total_name,
        total_value=total_value,
        total_timestamp=total_timestamp,
        previous_daily_value=previous_daily_value,
        mark_questionable=mark_questionable,
    )

    if current_daily.q.validity != ValidityKind_2025a.good or current_daily.t is None:
        _emit_warning(
            "Bootstrapped %s from Influx, but current daily %s is not yet good/timestamped; "
            "catch-up is deferred. total=%s total_ts=%s previous_daily=%s",
            total_attribute_id,
            daily_attribute_id,
            total_value,
            total_timestamp.isoformat(),
            previous_daily_value,
        )
        return

    if daily_sample is None:
        if not daily_attribute.store:
            _emit_warning(
                "Bootstrapped %s from total history only: paired daily %s has store=false, "
                "so cache was seeded from current daily=%s at %s. Downtime catch-up is unavailable.",
                total_attribute_id,
                daily_attribute_id,
                current_daily.actVal,
                current_daily.t.isoformat(),
            )
        else:
            _emit_warning(
                "Bootstrapped %s from total history only: no historical daily %s found in Influx, "
                "so cache was seeded from current daily=%s at %s. Downtime catch-up is unavailable.",
                total_attribute_id,
                daily_attribute_id,
                current_daily.actVal,
                current_daily.t.isoformat(),
            )
        return

    if mark_questionable:
        _emit_warning(
            "Bootstrapped %s with best-effort recovery: total=%s total_ts=%s previous_daily=%s from Influx, "
            "current_daily=%s at %s. The first MMTN call will continue with questionable quality.",
            total_attribute_id,
            total_value,
            total_timestamp.isoformat(),
            previous_daily_value,
            current_daily.actVal,
            current_daily.t.isoformat(),
        )
        return

    _emit_info(
        "Bootstrapped %s from Influx: total=%s at %s, previous daily=%s, current daily=%s at %s.",
        total_attribute_id,
        total_value,
        total_timestamp.isoformat(),
        previous_daily_value,
        current_daily.actVal,
        current_daily.t.isoformat(),
    )


def _paired_daily_name(total_name: str) -> str | None:
    if total_name == "SupWh":
        return "SupWhDay"
    if total_name == "DmdWh":
        return "DmdWhDay"
    return None


def _get_last_preferred_good(
    *,
    influx_client: InfluxClient,
    bucket: str,
    measurement: str,
    field: str,
    at_or_before: datetime | None = None,
) -> dict | None:
    sample = influx_client.get_last(
        bucket=bucket,
        measurement=measurement,
        field=field,
        tag_id=field,
        quality="good",
        at_or_before=at_or_before,
    )
    if sample is not None:
        return sample
    return influx_client.get_last(
        bucket=bucket,
        measurement=measurement,
        field=field,
        tag_id=field,
        at_or_before=at_or_before,
    )


def _requires_best_effort_recovery(previous_daily_value: int, current_daily: BCR_2025a) -> bool:
    if current_daily.q.validity != ValidityKind_2025a.good or current_daily.t is None:
        return False

    current_daily_value = current_daily.actVal
    same_direction = (
        previous_daily_value == 0
        or current_daily_value == 0
        or (current_daily_value > 0) == (previous_daily_value > 0)
    )
    return not (same_direction and abs(current_daily_value) >= abs(previous_daily_value))


def _fallback_daily_cache_value(current_daily: BCR_2025a) -> int:
    if current_daily.q.validity == ValidityKind_2025a.good and current_daily.t is not None:
        return int(current_daily.actVal)
    return 0


def _normalize_counter_value(raw_value: Any, attribute_id: str) -> int:
    if raw_value is None:
        raise ValueError(f"Influx bootstrap sample for {attribute_id} has no value.")
    return int(raw_value)


def _normalize_timestamp(raw_timestamp: Any, attribute_id: str) -> datetime:
    if not isinstance(raw_timestamp, datetime):
        raise ValueError(f"Influx bootstrap sample for {attribute_id} has no valid timestamp.")
    return raw_timestamp


def _emit_info(message: str, *args: object) -> None:
    _emit("info", message, *args)


def _emit_warning(message: str, *args: object) -> None:
    _emit("warning", message, *args)


def _emit_exception(message: str, *args: object) -> None:
    logger.exception(message, *args)
    loguru_logger.exception(_format_message(message, *args))


def _emit(level: str, message: str, *args: object) -> None:
    getattr(logger, level)(message, *args)
    getattr(loguru_logger, level)(_format_message(message, *args))


def _format_message(message: str, *args: object) -> str:
    return message % args if args else message
