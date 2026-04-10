from typing import List
from ..store.models import Partition

class PlatformProvider:
    """Abstract interface for OS-specific data fetching."""
    
    def get_partitions(self) -> List[Partition]:
        """Return all mounted physical partitions."""
        raise NotImplementedError
