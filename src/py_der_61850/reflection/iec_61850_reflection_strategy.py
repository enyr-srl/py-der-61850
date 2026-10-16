import importlib
from types import ModuleType
from typing import Dict, List, Type

from py_der_61850.models.config_visitor import ConfigVisitor
from py_der_61850.models.user_schema import Assignment, LNDeclaration
from py_der_61850.services.user_service import UserService

from .reflection_strategy import ReflectionStrategy


class IEC61850ReflectionStrategy(ReflectionStrategy):
    def __init__(
        self,
        lns_library_path: str,
        user_service: UserService,
        visitor: ConfigVisitor,
        lns_to_call: List[str] | None = None,
    ) -> None:
        super().__init__("app.tasks.task_opt")
        self._visitor = visitor
        self.__lns_library_path = lns_library_path
        self.__id_assignments: Dict[str, Assignment] = user_service.assignments()
        self.__ln_declarations: List[LNDeclaration] = user_service.ln_declarations()
        self.__user_ln_types: List[Type] = []
        self.__lns_to_call = lns_to_call

    def instantiate(self):
        root_module: ModuleType = importlib.import_module(self.__lns_library_path)
        lns_library: Dict[str, type] = self._get_module_classes(root_module)
        self.__set_user_lns(lns_library)
        self.__assign()

    def call(self):
        for cls in self.__user_ln_types:
            cls()

    def __assign(self) -> None:
        assignments = list(self.__id_assignments.values())
        for assignment in assignments:
            self.set_value(assignment.object, assignment.property, assignment.value.raw_value, assignment.value.type)

    def __set_user_lns(self, classes: Dict[str, type]) -> None:
        for ln_declaration in self.__ln_declarations:
            ln_type = self.__get_ln_class_from_type(ln_declaration.type, classes)
            ln_instance = ln_declaration.instance
            if not ln_type:
                continue
            cls = ln_type(self._visitor)
            if self.__lns_to_call is None:
                self.__user_ln_types.append(cls)
            else:
                if ln_instance in self.__lns_to_call:
                    self.__user_ln_types.append(cls)
            setattr(self._context, ln_instance, cls)

    def __get_ln_class_from_type(self, type: str, classes: Dict[str, type]) -> type | None:
        for class_name, class_type in classes.items():
            if class_name == type:
                return class_type
        return None
