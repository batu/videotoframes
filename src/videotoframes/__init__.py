"""videotoframes — standalone video → curated key frames CLI.

Public re-exports are deliberately empty: the tool's contract is its CLI
and the on-disk frame-manifest schema, not a Python API.
"""

from videotoframes._version import __version__

__all__ = ["__version__"]
