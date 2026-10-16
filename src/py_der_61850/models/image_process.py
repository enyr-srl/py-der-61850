from datetime import datetime, timezone
from typing import Any

from py_der_61850.models.user_schema import DataAttribute, DeviceRead, DeviceWrite


class ImageProcess:
    def __init__(self, data_attributes: dict[str, DataAttribute]):
        self.timestamp = datetime.now(timezone.utc)
        self.data_attributes = data_attributes

    def get_ids(self) -> list[str]:
        return list(self.data_attributes.keys())

    def _make_blocks(self, addresses: list[int], max_block_size: int = 10):
        """
        Raggruppa indirizzi in blocchi di lettura Modbus fino a max_block_size registri.
        Se ci sono gap tra indirizzi, includili per evitare richieste separate.
        """
        addresses = sorted(addresses)
        blocks = []
        i = 0
        n = len(addresses)

        while i < n:
            # inizia un blocco
            start = addresses[i]
            end = start
            j = i + 1

            # cerca di espandere il blocco
            while j < n and (addresses[j] - start + 1) <= max_block_size:
                # estendi end fino all'indirizzo più grande in questo blocco considerato
                end = addresses[j]
                j += 1

            count = end - start + 1
            blocks.append({"first_address": start, "count": count})

            # muovi i al successivo indirizzo che non è stato incluso nel blocco
            # se ci sono indirizzi intermedi mancanti che NON erano nella lista, li sono che verranno letti "inutilmente"
            # ma il blocco è fisso
            # troviamo il primo index k >= j che start al prossimo indirizzo > end
            i = j

        return blocks

    def get_address_blocks(self) -> list[dict[str, int]]:
        addresses = self.get_addresses()
        blocks = self._make_blocks(addresses)
        return blocks

    def get_addresses(self) -> list[int]:
        addresses = []
        for _, da in self.data_attributes.items():
            if da.mapping.source.protocol != "default":
                if da.mapping.source.config.ref_value.type == "float":
                    count = 2
                else:
                    count = 1
                for i in range(count):
                    addresses.append(int(da.mapping.source.config.address) + i)
        return addresses

    def read_blocks(self, blocks: list[dict[str, int]]) -> None:
        addresses = self.get_addresses()
        for _, da in self.data_attributes.items():
            if da.mapping.source.protocol != "default":
                da.mapping.source.config.read_blocks(blocks, addresses)
                break

    def get_image_status(self) -> list[DeviceRead]:
        device_readings: list[DeviceRead] = []
        for id, da in self.data_attributes.items():
            object, da_id = id.rsplit(".", 1)
            if da.mapping.source.protocol != "default":
                da.mapping.source.config.read()
                da_raw_value = da.value.raw_value
                if da_raw_value:
                    device_readings.append(
                        DeviceRead(object=object, property=da_id, value=da_raw_value, type=da.value.type)
                    )
        return device_readings

    def get_image_control(self) -> list[DeviceWrite]:
        # IMMAGINE DI CONTROLLO
        result: list[DeviceWrite] = []
        for id, da in self.data_attributes.items():
            if da.mapping.target.protocol != "default":
                device_write = DeviceWrite(id=id, da=da)
                result.append(device_write)
        return result

    def get_image_process(self) -> list[DeviceWrite]:
        # IMMAGINE DI PROCESSO SIA STATUS CHE CONTROL
        result: list[DeviceWrite] = []
        for id, da in self.data_attributes.items():
            if da.value.type != "reference":
                device_write = DeviceWrite(id=id, da=da)
                result.append(device_write)
        return result

    def write_value(self, attribute_id: str, value: Any) -> None:
        if value is None:
            return
        if attribute_id in self.data_attributes:
            self.data_attributes[attribute_id].value.raw_value = str(value)
        else:
            raise KeyError(f"Attribute ID {attribute_id} not found in image process.")

    def set_timestamp(self) -> None:
        self.timestamp = datetime.now(timezone.utc)

    def get_timestamp(self) -> datetime:
        return self.timestamp
