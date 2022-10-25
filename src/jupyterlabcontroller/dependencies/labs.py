from typing import Dict

from ..models.v1.external.userdata import UserData


class LabDependency:
    def __call__(self) -> Dict[str, UserData]:
        labs: Dict[str, UserData] = {}
        return labs


lab_dependency = LabDependency()
