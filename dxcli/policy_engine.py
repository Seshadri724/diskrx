import logging
import os
import sys
from typing import Dict, List, Optional

import yaml

from .store.models import DirNode, PolicyViolation, StaleFile, UnrotatedLog

logger = logging.getLogger(__name__)


def _path_in_scope(candidate: str, root: str) -> bool:
    if root == "*":
        return True
    cand = os.path.abspath(candidate)
    base = os.path.abspath(root)
    if os.name == "nt":
        cand = cand.lower()
        base = base.lower()
    if cand == base:
        return True
    return cand.startswith(base.rstrip(os.sep) + os.sep)


class PolicyEngine:
    """
    Evaluates disk rules against scanned data.
    Implements 'Disk Policy as Code' (Mitchell Hashimoto style).
    """

    def __init__(self, policy_path: Optional[str] = None):
        self.policy_path = policy_path or os.path.expanduser("~/.dx/policies.yaml")
        self.rules: List[Dict] = []
        self.load_warnings: List[str] = []
        self._load_rules()

    def _load_rules(self) -> None:
        """Load rules from the policy file.

        If the file is missing, that is normal — no rules apply.
        If the file exists but is malformed, warn visibly so operators know
        their policies are NOT being enforced.
        """
        if not os.path.exists(self.policy_path):
            return

        try:
            with open(self.policy_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            msg = f"[dxcli] WARNING: policies.yaml is malformed: {e}. No policies will be enforced."
            logger.warning(msg)
            print(msg, file=sys.stderr)
            self.load_warnings.append(str(e))
            return
        except OSError as e:
            msg = f"[dxcli] WARNING: Could not read policies.yaml: {e}. No policies will be enforced."
            logger.warning(msg)
            print(msg, file=sys.stderr)
            self.load_warnings.append(str(e))
            return

        if not isinstance(raw, dict):
            msg = "[dxcli] WARNING: policies.yaml must be a YAML mapping. No policies will be enforced."
            logger.warning(msg)
            print(msg, file=sys.stderr)
            return

        rules = raw.get("rules", [])
        if not isinstance(rules, list):
            msg = "[dxcli] WARNING: 'rules' key in policies.yaml must be a list."
            logger.warning(msg)
            print(msg, file=sys.stderr)
            return

        self.rules = rules

    def evaluate(
        self,
        top_dirs: List[DirNode],
        logs: List[UnrotatedLog],
        stales: List[StaleFile],
    ) -> List[PolicyViolation]:
        violations: List[PolicyViolation] = []

        for rule in self.rules:
            if not isinstance(rule, dict):
                continue

            rule_type = rule.get("type", "limit")
            target_path = rule.get("path", "*")

            if rule_type == "limit":
                max_size_gb = rule.get("max_size_gb", 10)
                max_size_bytes = max_size_gb * (1024**3)

                for d in top_dirs:
                    if _path_in_scope(d.path, target_path):
                        if d.size_bytes > max_size_bytes:
                            violations.append(
                                PolicyViolation(
                                    rule_name=rule.get("name", "Size Limit"),
                                    path=d.path,
                                    message=f"Directory exceeds policy limit of {max_size_gb}GB",
                                    severity=(
                                        "critical"
                                        if d.size_bytes > max_size_bytes * 1.5
                                        else "warning"
                                    ),
                                    suggested_action=rule.get(
                                        "action", "Cleanup or archive"
                                    ),
                                )
                            )

            elif rule_type == "stale":
                max_age_days = rule.get("max_age_days", 30)
                for s in stales:
                    if _path_in_scope(s.path, target_path):
                        if s.days_stale > max_age_days:
                            violations.append(
                                PolicyViolation(
                                    rule_name=rule.get("name", "Stale Policy"),
                                    path=s.path,
                                    message=f"File is older than {max_age_days} days",
                                    severity="warning",
                                    suggested_action="Delete or move to cold storage",
                                )
                            )

        return violations
