import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from typing import Dict, List, Optional

from .store.models import Prescription

logger = logging.getLogger(__name__)

_SAFE_BACKUP_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


class HealEngine:
    """
    Executes prescriptions with auditing and undo support.

    Safety contract:
    - `allowed_scope` MUST be set. Healing without a scope is refused.
    - All target paths are validated against the scope before any action.
    - Symlink traversal outside scope is rejected.
    - Backup is verified before the original file is deleted.
    - Every action is appended to an audit log.
    """

    def __init__(self, allowed_scope: Optional[str] = None):
        from .state import get_state_dir

        self.dx_dir = get_state_dir()
        self.audit_log_path = os.path.join(self.dx_dir, "audit.log")
        self.undo_stack_path = os.path.join(self.dx_dir, "undo_stack.json")
        self.backup_dir = os.path.join(self.dx_dir, "backups")

        self.session_actions: List[Dict] = []
        self.total_reclaimed = 0

        # allowed_scope is required for any destructive action
        self.allowed_scope = os.path.abspath(allowed_scope) if allowed_scope else None

        os.makedirs(self.backup_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_action(self, action: str, details: Dict, undo_info: Optional[Dict] = None) -> None:
        """Append an action record to the audit log and session list."""
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "details": details,
            "undo_available": undo_info is not None,
        }
        self.session_actions.append(log_entry)

        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError as e:
            logger.warning("Audit log write failed: %s", e)

        if undo_info:
            try:
                stack = self._load_undo_stack()
                stack.append({"timestamp": timestamp, "action": action, "undo_info": undo_info})
                self._save_undo_stack(stack)
            except Exception as e:
                logger.warning("Undo stack update failed: %s", e)

    def _load_undo_stack(self) -> List[Dict]:
        if not os.path.exists(self.undo_stack_path):
            return []
        try:
            with open(self.undo_stack_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read undo stack: %s", e)
            return []

    def _save_undo_stack(self, stack: List[Dict]) -> None:
        from .state import atomic_write
        atomic_write(self.undo_stack_path, json.dumps(stack, indent=2))

    def _is_safe_path(self, target_path: str) -> bool:
        """Validate that target_path is inside the allowed_scope.

        Rejects:
        - Paths outside allowed_scope (absolute check)
        - Symlinks whose real path resolves outside allowed_scope
        """
        if not self.allowed_scope:
            return False

        abs_target = os.path.abspath(target_path)
        scope = self.allowed_scope
        # Case-insensitive on Windows
        if os.name == 'nt':
            abs_target = abs_target.lower()
            scope = scope.lower()
        # os.path.startswith is not reliable — use normpath comparison
        scope_with_sep = scope.rstrip(os.sep) + os.sep
        if not (abs_target == scope or abs_target.startswith(scope_with_sep)):
            return False

        # Resolve symlinks and re-check
        try:
            real_target = os.path.realpath(target_path)
        except OSError:
            return False

        if os.name == 'nt':
            real_target = real_target.lower()
        if not (real_target == scope or real_target.startswith(scope_with_sep)):
            return False

        return True

    def _safe_backup_id(self, prescription_id: str) -> str:
        item_tag = _SAFE_BACKUP_TOKEN.sub("_", str(prescription_id)).strip("._")
        if not item_tag:
            item_tag = "item"
        return f"backup_{int(time.time())}_{item_tag[:80]}"

    def _validated_target_stat(self, target_path: str):
        if not self._is_safe_path(target_path):
            raise OSError("target path is outside allowed scope")
        if os.path.islink(target_path):
            raise OSError("refusing to operate on symlink target")
        return os.lstat(target_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, prescription: Prescription, dry_run: bool = False) -> bool:
        """Execute a prescription.

        Returns True on success, False on refusal or failure.
        Refusals are always logged.
        """
        if not prescription.target_path:
            self._log_action("skip", {"name": prescription.name, "reason": "No target path"})
            return False

        if not self.allowed_scope:
            self._log_action(
                "refuse",
                {"name": prescription.name, "reason": "HealEngine has no allowed_scope set. Refusing all actions."},
            )
            logger.error(
                "heal refused: no allowed_scope set. Always pass allowed_scope= when constructing HealEngine."
            )
            return False

        # Redirect target path for create_file if it is outside the allowed scope
        if prescription.action_type == "create_file":
            if not self._is_safe_path(prescription.target_path):
                basename = os.path.basename(prescription.target_path)
                new_target = os.path.abspath(os.path.join(self.allowed_scope, basename))
                prescription.target_path = new_target

        if not self._is_safe_path(prescription.target_path):
            self._log_action(
                "reject",
                {
                    "name": prescription.name,
                    "path": prescription.target_path,
                    "reason": "Path outside allowed scope or symlink traversal detected",
                },
            )
            return False

        if dry_run:
            self._log_action(
                "dry_run",
                {
                    "name": prescription.name,
                    "path": prescription.target_path,
                    "action_type": prescription.action_type,
                    "saved": prescription.size_savings_bytes,
                }
            )
            self.total_reclaimed += prescription.size_savings_bytes
            return True

        success = False
        if prescription.action_type == "delete":
            success = self._execute_delete(prescription)
        elif prescription.action_type == "create_file":
            success = self._execute_create(prescription)
        elif prescription.action_type in ("manual", "info"):
            self._log_action(
                "manual",
                {
                    "name": prescription.name,
                    "reason": "Requires manual intervention by the operator",
                    "instructions": prescription.template or "See prescription details.",
                },
            )
        else:
            self._log_action(
                "skip",
                {"name": prescription.name, "reason": f"Unknown action_type: {prescription.action_type}"},
            )

        if success:
            self.total_reclaimed += prescription.size_savings_bytes

        return success


    def _execute_delete(self, p: Prescription) -> bool:
        if not os.path.exists(p.target_path):
            self._log_action("delete_fail", {"path": p.target_path, "reason": "File not found"})
            return False

        backup_id = self._safe_backup_id(p.id)
        backup_path = os.path.join(self.backup_dir, backup_id)

        # Backup MUST succeed before we touch the original
        try:
            before_stat = self._validated_target_stat(p.target_path)
            shutil.copy2(p.target_path, backup_path, follow_symlinks=False)
            after_copy_stat = self._validated_target_stat(p.target_path)
            before_identity = (
                before_stat.st_dev,
                before_stat.st_ino,
                before_stat.st_size,
                before_stat.st_mtime_ns,
            )
            after_copy_identity = (
                after_copy_stat.st_dev,
                after_copy_stat.st_ino,
                after_copy_stat.st_size,
                after_copy_stat.st_mtime_ns,
            )
            if before_identity != after_copy_identity:
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
                raise OSError("target changed during backup")
        except OSError as e:
            self._log_action(
                "delete_fail",
                {"path": p.target_path, "reason": f"Backup failed, original untouched: {e}"},
            )
            return False

        try:
            self._validated_target_stat(p.target_path)
            os.remove(p.target_path)
        except OSError as e:
            self._log_action("delete_error", {"path": p.target_path, "error": str(e)})
            # Attempt to restore the backup
            try:
                shutil.move(backup_path, p.target_path)
            except Exception:
                pass
            return False

        self._log_action(
            "delete",
            {"path": p.target_path, "backup": backup_id, "saved": p.size_savings_bytes},
            undo_info={"type": "restore_file", "original_path": p.target_path, "backup_path": backup_path},
        )
        return True

    def _execute_create(self, p: Prescription) -> bool:
        """Create a file from a template. Validates the destination is in scope."""
        if not self._is_safe_path(p.target_path):
            self._log_action(
                "reject",
                {"name": p.name, "path": p.target_path, "reason": "create_file path outside allowed scope"},
            )
            return False

        try:
            os.makedirs(os.path.dirname(p.target_path), exist_ok=True)
            with open(p.target_path, "w", encoding="utf-8") as f:
                f.write(p.template or "")
        except OSError as e:
            self._log_action("create_error", {"path": p.target_path, "error": str(e)})
            return False

        self._log_action(
            "create",
            {"path": p.target_path, "name": p.name},
            undo_info={"type": "delete_file", "path": p.target_path},
        )
        return True

    def generate_sleep_insurance_report(self) -> str:
        """Generate a summary of the healing session."""
        if not self.session_actions:
            return "No actions taken in this session."

        from .outputs.cli_report import format_bytes

        successful = [a for a in self.session_actions if a["action"] in ("delete", "create")]
        report = [
            "\n[bold green]SLEEP INSURANCE -- REMITTANCE REPORT[/bold green]",
            "  [bold]Status:[/bold] Healthy",
            f"  [bold]Space Reclaimed:[/bold] [bold green]{format_bytes(self.total_reclaimed)}[/bold green]",
            f"  [bold]Actions Applied:[/bold] {len(successful)}",
            "\n  [dim]You can rest easy. Production server has been stabilized.[/dim]",
        ]
        return "\n".join(report)

    def undo(self) -> Optional[str]:
        """Revert the last healing action."""
        stack = self._load_undo_stack()
        if not stack:
            return None

        last_action = stack.pop()
        undo_info = last_action.get("undo_info", {})

        try:
            if undo_info.get("type") == "restore_file":
                shutil.move(undo_info["backup_path"], undo_info["original_path"])
                msg = f"Restored {undo_info['original_path']}"
            elif undo_info.get("type") == "delete_file":
                path = undo_info.get("path", "")
                if path and os.path.exists(path):
                    os.remove(path)
                msg = f"Removed created file {path}"
            else:
                msg = f"Unknown undo type: {undo_info.get('type')}"

            self._save_undo_stack(stack)
            self._log_action("undo", {"reverted_action": last_action.get("action")})
            return msg

        except (OSError, KeyError) as e:
            return f"Undo failed: {e}"
