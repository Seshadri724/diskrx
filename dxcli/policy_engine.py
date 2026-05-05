import os
import yaml
from typing import List, Dict, Optional
from .store.models import DirNode, UnrotatedLog, StaleFile, PolicyViolation

class PolicyEngine:
    """
    Evaluates disk rules against scanned data.
    Implements 'Disk Policy as Code' (Mitchell Hashimoto style).
    """
    def __init__(self, policy_path: Optional[str] = None):
        self.policy_path = policy_path or os.path.expanduser("~/.dx/policies.yaml")
        self.rules = self._load_rules()

    def _load_rules(self) -> List[Dict]:
        if not os.path.exists(self.policy_path):
            # Return empty or some very basic default internal rules
            return []
        
        try:
            with open(self.policy_path, "r") as f:
                config = yaml.safe_load(f)
                return config.get("rules", [])
        except Exception:
            return []

    def evaluate(self, top_dirs: List[DirNode], logs: List[UnrotatedLog], stales: List[StaleFile]) -> List[PolicyViolation]:
        violations = []
        
        for rule in self.rules:
            rule_type = rule.get("type", "limit")
            target_path = rule.get("path", "*")
            
            if rule_type == "limit":
                max_size_gb = rule.get("max_size_gb", 10)
                max_size_bytes = max_size_gb * (1024**3)
                
                for d in top_dirs:
                    if target_path == "*" or d.path.startswith(target_path):
                        if d.size_bytes > max_size_bytes:
                            violations.append(PolicyViolation(
                                rule_name=rule.get("name", "Size Limit"),
                                path=d.path,
                                message=f"Directory exceeds policy limit of {max_size_gb}GB",
                                severity="critical" if d.size_bytes > max_size_bytes * 1.5 else "warning",
                                suggested_action=rule.get("action", "Cleanup or archive")
                            ))
            
            elif rule_type == "stale":
                max_age_days = rule.get("max_age_days", 30)
                for s in stales:
                    if target_path == "*" or s.path.startswith(target_path):
                        if s.days_stale > max_age_days:
                            violations.append(PolicyViolation(
                                rule_name=rule.get("name", "Stale Policy"),
                                path=s.path,
                                message=f"File is older than {max_age_days} days",
                                severity="warning",
                                suggested_action="Delete or move to cold storage"
                            ))
                            
        return violations
