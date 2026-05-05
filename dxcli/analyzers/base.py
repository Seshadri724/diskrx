from abc import ABC, abstractmethod
from typing import List
from ..store.models import DirNode, UnrotatedLog, StaleFile, Prescription, PolicyViolation

class AnalyzerPlugin(ABC):
    """
    Base class for dxcli plugins (Shopify/Tobias Lütke style).
    Community members can inherit from this to add logic for specific stacks.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def analyze(self, top_dirs: List[DirNode], logs: List[UnrotatedLog], stales: List[StaleFile]) -> List[Prescription]:
        """
        Return a list of prescriptions based on the scan results.
        """
        pass
