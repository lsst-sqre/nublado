from ..models.v1.external.userdata import UserMap


class LabDependency:
    def __call__(self) -> UserMap:
        labs: UserMap = {}
        return labs


lab_dependency = LabDependency()
