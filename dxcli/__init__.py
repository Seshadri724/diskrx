"""
dxcli
Intelligent disk diagnostics for SREs.
"""

from importlib.metadata import version, PackageNotFoundError
try:
    __version__ = version("dxcli")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

