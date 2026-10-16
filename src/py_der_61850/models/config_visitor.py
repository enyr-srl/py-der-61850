class ConfigVisitor:

    def __init__(
        self,
        user_config: dict | None = None,
        rec_config: dict | None = None,
        users_config: list[dict] | None = None,
    ) -> None:
        self._user_config = user_config or {}
        self._rec_config = rec_config or {}
        self._users_config = users_config or []

    def get_users_length(self) -> int:
        users_length = len(self._rec_config.get("users", []))
        return users_length

    def get_market_zone_ids(self) -> list[str]:
        zones: set[str] = set()

        for user_config in [self._user_config, *self._users_config]:
            zones.update(self._extract_market_zone_ids(user_config))

        return sorted(zones)

    def has_data_attribute(
        self,
        *,
        device_id: str,
        ln_id: str,
        do_id: str,
        da_id: str,
        user_id: str | None = None,
    ) -> bool:
        for user_config in [self._user_config, *self._users_config]:
            if not user_config:
                continue
            if user_id is not None and user_config.get("id") != user_id:
                continue
            if self._config_has_data_attribute(
                user_config,
                device_id=device_id,
                ln_id=ln_id,
                do_id=do_id,
                da_id=da_id,
            ):
                return True
        return False

    @staticmethod
    def _extract_market_zone_ids(user_config: dict) -> set[str]:
        zones: set[str] = set()

        for device in user_config.get("devices", []):
            for logical_node in device.get("lns", []):
                for data_object in logical_node.get("dos", []):
                    if data_object.get("id") != "AreaEpsMrkZnId":
                        continue

                    for data_attribute in data_object.get("das", []):
                        if data_attribute.get("id") != "dataNs":
                            continue

                        zone = data_attribute.get("value")
                        if zone:
                            zones.add(str(zone).upper())

        return zones

    @staticmethod
    def _config_has_data_attribute(
        user_config: dict,
        *,
        device_id: str,
        ln_id: str,
        do_id: str,
        da_id: str,
    ) -> bool:
        for device in user_config.get("devices", []):
            if device.get("id") != device_id:
                continue
            for logical_node in device.get("lns", []):
                if logical_node.get("id") != ln_id:
                    continue
                for data_object in logical_node.get("dos", []):
                    if data_object.get("id") != do_id:
                        continue
                    for data_attribute in data_object.get("das", []):
                        if data_attribute.get("id") == da_id:
                            return True
        return False
