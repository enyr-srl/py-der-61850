import importlib
import inspect
import pkgutil
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Dict

from loguru import logger

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a


class ReflectionStrategy(ABC):
    def __init__(self, context_path: str):
        self._context = importlib.import_module(context_path)

    @abstractmethod
    def instantiate(self):
        raise NotImplementedError

    @abstractmethod
    def call(self):
        raise NotImplementedError

    def _get_object_from_expression(self, expression: str) -> Any | None:
        root_obj, *sub_objs = expression.split(".")
        try:
            obj = getattr(self._context, root_obj)
            for sub_obj in sub_objs:
                obj = getattr(obj, sub_obj)
            return obj
        except Exception as e:
            logger.error(f"Error getting object from expression '{expression}': {e}")
            return None

    def set_value(self, object: str, property: str, value: str, type: str):
        obj = self._get_object_from_expression(object)
        if obj:
            data = self.__cast_value(value, type)
            setattr(obj, property, data)
            # FIXME: Hardcoded validity and timestamp for now
            if hasattr(obj, "q") and obj.q is not None:
                obj.q.validity = ValidityKind_2025a.good
            if hasattr(obj, "t"):        
                obj.t = datetime.now(timezone.utc)

    def get_value(self, id: str) -> Any | None:
        return self._get_object_from_expression(id)

    def _get_module_classes(self, root_module: ModuleType) -> Dict[str, type]:
        classes: Dict[str, type] = {}
        for loader, module_name, is_pkg in pkgutil.iter_modules(root_module.__path__):
            full_module_name = f"{root_module.__name__}.{module_name}"
            module = importlib.import_module(full_module_name)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Ensure class is defined in this module (not imported from elsewhere)
                if obj.__module__ == full_module_name:
                    classes[name] = obj
        return classes

    def __cast_value(self, data: str, type: str) -> Any:
        if type == "int":
            return int(data)
        if type == "bool":
            return bool(data)
        if type == "float":
            return float(data)
        if type == "string":
            return data
        if type == "reference":
            obj: Any | None = self._get_object_from_expression(data)
            if obj:
                return obj
            return data
        raise ValueError(f"Unknown value type {type}")
