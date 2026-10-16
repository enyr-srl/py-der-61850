from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class Quality_2025a(DOType):
    """Quality contains data that describe the quality of the data from the server. Quality of the data is also related to the mode of a logical node. Further details can be found in IEC 61850-7-4. The different quality attributes are not independent. The default value shall be applied if the functionality of the related attribute is not supported. The mapping may specify to exclude the attribute from the message if it is not supported or if the default value applies."""

    def __init__(
        self,
        value: int = 1,
    ) -> None:
        self.validity: ValidityKind_2025a = ValidityKind_2025a(value)  # Validity of the data
