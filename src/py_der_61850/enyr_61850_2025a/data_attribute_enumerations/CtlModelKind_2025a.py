from enum import Enum

# Enum per ctlModel (definito in 7-3 Tabella 99) [9]
class CtlModelKind_2025a(Enum):
    status_only = 0
    direct_normal = 1
    sbo_normal = 2
    direct_enhanced = 3
    sbo_enhanced = 4
