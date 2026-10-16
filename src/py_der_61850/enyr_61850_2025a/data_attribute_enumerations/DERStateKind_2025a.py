from enum import Enum


class DERStateKind_2025a(Enum):
    on_but_disconnected_and_not_ready = 1
    starting_up = 2
    disconnected_and_available = 3
    disconnected_and_authorized = 4
    synchronizing = 5
    running = 6
    stopping_and_disconnecting_under_emergency_conditions = 7
    stopping = 8
    disconnected_and_blocked = 9
    disconnected_and_in_maintenance = 10
    failed = 11
    Not_applicable_or_not_known = 98
