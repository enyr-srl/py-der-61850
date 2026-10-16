from enum import Enum


class PhaseKind_2025a(Enum):
    not_applicable_or_not_know = 98
    single_phase_to_neutral = 1
    split_phase = 2
    two_phase = 3
    three_phase_delta = 4
    three_phase_wye_four_wires = 5
    three_phase_wye_four_five = 6
    DC = 9
