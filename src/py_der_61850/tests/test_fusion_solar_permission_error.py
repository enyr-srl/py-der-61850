import unittest

from py_der_61850.clients.fusion_solar_client import FusionSolarClient

# Regressione produzione PODXX3 (16/06/2026): Huawei restituisce failCode==2 sia per i
# duplicati sia per "Exist no permission plants". Classificare il permission-error come
# duplicato lo faceva ritentare ogni 10s, bruciando la quota della control API
# (100 chiamate/giorno -> failCode 407) e affamando anche gli altri POD sullo stesso account.
PERMISSION_DENIED = {
    "data": None,
    "failCode": 2,
    "message": "Exist no permission plants, plantCodes: [NE=900000001]",
    "success": False,
}

REAL_DUPLICATE = {
    "success": False,
    "failCode": 2,
    "message": "Failed to deliver the battery charge/discharge task.",
    "data": {
        "requestID": None,
        "result": [
            {
                "dispatchResult": 1,
                "subTaskId": None,
                "description": "The duplicate task is running, battery DN: NE=900000005",
            }
        ],
    },
}


class FusionSolarPermissionErrorTests(unittest.TestCase):
    def test_permission_error_is_not_classified_as_duplicate(self) -> None:
        self.assertFalse(FusionSolarClient._is_charge_discharge_duplicate(PERMISSION_DENIED))

    def test_real_duplicate_is_still_classified_as_duplicate(self) -> None:
        self.assertTrue(FusionSolarClient._is_charge_discharge_duplicate(REAL_DUPLICATE))


if __name__ == "__main__":
    unittest.main()
