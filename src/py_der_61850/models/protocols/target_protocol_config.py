from abc import abstractmethod

from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType

from .protocol_config import ProtocolConfig


class TargetProtocolConfig(ProtocolConfig):
    @abstractmethod
    def write(self, do_type: DOType):
        pass
