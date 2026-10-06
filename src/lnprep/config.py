"""
Configuration constants and runtime state for lnprep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


GUIDE_FILENAME = "LECTURE_NOTES_GUIDE.md"
FORMAT_FILENAME = "NOTES_FORMAT.md"
CACHE_FILENAME = ".citation_cache.json"
OVERRIDE_LOG = ".reference_overrides.log"

DEFAULT_TTL_DAYS = 180
DEFAULT_HTTP_TIMEOUT = 15
MAX_DOWNLOAD_BYTES = 3_000_000

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
CROSSREF_UA = "lnprep/1.0.0 (mailto:loh.wilson@gmail.com)"


@dataclass
class Config:
    verbose: bool = False
    debug: bool = False
    custom_options: Dict[str, Any] = field(default_factory=dict)


# Global singleton configuration object
config = Config()
