import os
import logging
from typing import List
from ..store.models import Prescription

logger = logging.getLogger(__name__)


class RuleEngine:
    """
    Pattern-based rule engine for stack-specific recommendations.
    Matches directory structures/files to known space-saving actions.
    """

    RULES = [
        {
            "name": "Node.js Package Cache",
            "trigger_files": ["package.json"],
            "trigger_dirs": ["node_modules"],
            "prescription": {
                "id": "npm_cache",
                "name": "Clean npm cache",
                "template": "npm cache clean --force",
                "risk": "safe",
                "action_type": "manual",
            },
        },
        {
            "name": "Python Bytecode",
            "trigger_dirs": ["__pycache__"],
            "prescription": {
                "id": "py_cache",
                "name": "Clear Python bytecode cache",
                "template": 'find . -name "*.pyc" -delete',
                "risk": "safe",
                "action_type": "manual",
            },
        },
        {
            "name": "Docker Build Context",
            "trigger_files": ["Dockerfile"],
            "prescription": {
                "id": "docker_ignore",
                "name": "Optimize Docker build context",
                "template": "# Add large unnecessary files to .dockerignore to speed up builds and save space.",
                "risk": "safe",
                "action_type": "info",
            },
        },
    ]

    def __init__(self):
        pass

    def evaluate(self, path: str) -> List[Prescription]:
        prescriptions = []

        # Check for presence of trigger files/dirs
        try:
            items = os.listdir(path)
            for rule in self.RULES:
                match = False

                # Check trigger files
                if "trigger_files" in rule:
                    if any(f in items for f in rule["trigger_files"]):
                        match = True

                # Check trigger dirs
                if "trigger_dirs" in rule:
                    if any(
                        d in items and os.path.isdir(os.path.join(path, d))
                        for d in rule["trigger_dirs"]
                    ):
                        match = True

                if match:
                    p_data = rule["prescription"]
                    prescriptions.append(
                        Prescription(
                            id=p_data["id"],
                            name=p_data["name"],
                            description=rule["name"],
                            category="rules",
                            severity="low",
                            template=p_data["template"],
                            risk=p_data["risk"],
                            size_savings_bytes=0,  # Estimated
                            action_type=p_data["action_type"],
                            target_path=path,
                            is_safe=False,
                        )
                    )
        except OSError as exc:
            logger.warning("Rule evaluation skipped for %s: %s", path, exc)

        return prescriptions
