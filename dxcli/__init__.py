"""
dxcli
The disk doctor for your CI pipeline and dev box.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("diskrx")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
