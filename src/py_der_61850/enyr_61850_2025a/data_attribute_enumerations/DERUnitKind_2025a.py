from enum import Enum


class DERUnitKind_2025a(Enum):
    not_applicable_or_unknown = 0
    diesel_gas_engine = 1
    gas_turbine_engine = 2
    PV = 3
    PV_plus_storage = 4
    lithium_ion_battery_storage = 5
    fuel_cell = 6
    hydro_generator = 7
    wind_turbine = 8
    flow_battery_storage = 9
    air_compression_storage = 10
    flywheel_storage = 11
    capacitor_storage = 12
    vehicle_to_grid_V2G = 13
    mixed_hybrid_DER = 50
    not_applicable_or_not_known = 98
    other = 99
