import sys
from .base import PlatformProvider

def get_platform_provider() -> PlatformProvider:
    if sys.platform == 'win32':
        from .windows import WindowsProvider
        return WindowsProvider()
    else:
        # Default to Linux/Unix style for Mac and Linux
        from .linux import LinuxProvider
        return LinuxProvider()

provider = get_platform_provider()
