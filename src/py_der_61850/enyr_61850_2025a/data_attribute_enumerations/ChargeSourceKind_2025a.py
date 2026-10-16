from enum import Enum


class ChargeSourceKind_2025a(Enum):
    Mode_A = 1  # Storage may not export to grid, but may charge
    Mode_B = 2  # Storage may export to grid, but not charge
    Mode_C = 3  # Storage may both charge or discharge from the grid
