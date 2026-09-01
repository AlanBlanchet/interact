"""Apply persisted CLI configuration before importing command dependencies."""

from interact.config import Config, UserConfig, load_dotenv_for_cli


def apply_command_environment() -> None:
    """Apply persisted command configuration before deferred dependencies load or execute."""
    UserConfig.apply()
    load_dotenv_for_cli()


apply_command_environment()

__all__ = ["Config", "UserConfig", "apply_command_environment"]
