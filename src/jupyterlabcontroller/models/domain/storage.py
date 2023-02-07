from dataclasses import dataclass
from typing import List, Optional

from ...models.v1.lab import UserInfo


@dataclass
class GafaelfawrCache:
    user: Optional[UserInfo] = None
    scopes: Optional[List[str]] = None
