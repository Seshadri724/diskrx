import os
import tempfile


def get_state_dir() -> str:
    """Returns the centralized, secure state directory for dxcli."""
    home = os.path.expanduser("~")
    dx_dir = os.path.join(home, ".dx")
    
    # Secure defaults: 0700 for state directory
    if not os.path.exists(dx_dir):
        os.makedirs(dx_dir, mode=0o700, exist_ok=True)
    elif os.name != 'nt':
        try:
            os.chmod(dx_dir, 0o700)
        except OSError:
            pass # Handle readonly or permission denied
            
    return dx_dir

def atomic_write(filepath: str, content: str, mode: int = 0o600):
    """Writes to a file atomically, ensuring no partial writes or corruption.
    Creates a temporary file, writes, then renames/replaces the target file.
    """
    dirname = os.path.dirname(filepath) or "."
    if not os.path.exists(dirname):
        os.makedirs(dirname, mode=0o700, exist_ok=True)
        
    fd, temp_path = tempfile.mkstemp(dir=dirname, text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Apply secure permissions to the temp file
        if os.name != 'nt':
            os.chmod(temp_path, mode)
            
        # Atomic replace
        os.replace(temp_path, filepath)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
