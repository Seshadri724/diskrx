import os
import shutil
import json
import time
from datetime import datetime
from typing import List, Dict, Optional
from .store.models import Prescription

class HealEngine:
    """
    Executes prescriptions with auditing and undo support.
    """
    def __init__(self):
        self.home = os.path.expanduser("~")
        self.dx_dir = os.path.join(self.home, ".dx")
        self.audit_log_path = os.path.join(self.dx_dir, "audit.log")
        self.undo_stack_path = os.path.join(self.dx_dir, "undo_stack.json")
        self.backup_dir = os.path.join(self.dx_dir, "backups")
        
        os.makedirs(self.dx_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

    def _log_action(self, action: str, details: Dict, undo_info: Optional[Dict] = None):
        """Log action to audit.log and update undo stack."""
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "details": details,
            "undo_available": undo_info is not None
        }
        
        with open(self.audit_log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
            
        if undo_info:
            stack = self._load_undo_stack()
            stack.append({
                "timestamp": timestamp,
                "action": action,
                "undo_info": undo_info
            })
            self._save_undo_stack(stack)

    def _load_undo_stack(self) -> List[Dict]:
        if os.path.exists(self.undo_stack_path):
            try:
                with open(self.undo_stack_path, "r") as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_undo_stack(self, stack: List[Dict]):
        with open(self.undo_stack_path, "w") as f:
            json.dump(stack, f, indent=2)

    def execute(self, prescription: Prescription) -> bool:
        """Execute a prescription and store undo info."""
        if not prescription.target_path:
            # For recommendations that don't have a direct target (like template instructions)
            self._log_action("skip", {"name": prescription.name, "reason": "No target path"})
            return False

        if prescription.action_type == "delete":
            return self._execute_delete(prescription)
        elif prescription.action_type == "create_file":
            return self._execute_create(prescription)
        
        return False

    def _execute_delete(self, p: Prescription) -> bool:
        if not os.path.exists(p.target_path):
            self._log_action("delete_fail", {"path": p.target_path, "reason": "File not found"})
            return False
            
        # Create backup
        backup_id = f"backup_{int(time.time())}_{p.id}"
        backup_path = os.path.join(self.backup_dir, backup_id)
        
        try:
            shutil.copy2(p.target_path, backup_path)
            os.remove(p.target_path)
            
            self._log_action("delete", {"path": p.target_path, "backup": backup_id}, undo_info={
                "type": "restore_file",
                "original_path": p.target_path,
                "backup_path": backup_path
            })
            return True
        except Exception as e:
            self._log_action("delete_error", {"path": p.target_path, "error": str(e)})
            return False

    def _execute_create(self, p: Prescription) -> bool:
        # Currently, 'create_file' like logrotate configs might require root.
        # We'll try to write it.
        try:
            os.makedirs(os.path.dirname(p.target_path), exist_ok=True)
            with open(p.target_path, "w") as f:
                f.write(p.template)
            
            self._log_action("create", {"path": p.target_path}, undo_info={
                "type": "delete_file",
                "path": p.target_path
            })
            return True
        except Exception as e:
            self._log_action("create_error", {"path": p.target_path, "error": str(e)})
            return False

    def undo(self) -> Optional[str]:
        """Revert the last action. Returns a message about what was undone."""
        stack = self._load_undo_stack()
        if not stack:
            return None
            
        last_action = stack.pop()
        undo_info = last_action["undo_info"]
        
        try:
            if undo_info["type"] == "restore_file":
                shutil.move(undo_info["backup_path"], undo_info["original_path"])
                msg = f"Restored {undo_info['original_path']}"
            elif undo_info["type"] == "delete_file":
                if os.path.exists(undo_info["path"]):
                    os.remove(undo_info["path"])
                msg = f"Removed created file {undo_info['path']}"
            else:
                msg = "Unknown undo type"
                
            self._save_undo_stack(stack)
            self._log_action("undo", {"reverted_action": last_action["action"]})
            return msg
        except Exception as e:
            return f"Undo failed: {e}"
