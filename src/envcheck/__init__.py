"""envcheck: declare the dev environment a project needs, then check it locally or in CI."""

from envcheck.config import Config, load_config, parse_config
from envcheck.result import CheckResult

__version__ = "0.1.0"
__all__ = ["CheckResult", "Config", "load_config", "parse_config"]
