import os
import logging
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import PostgresDsn, validator, Field, SecretStr

# Load .env file at the beginning if you are not using Docker or another env management system
# For production, it's often better to rely on environment variables set by the system/orchestrator.
# load_dotenv() # Uncomment if you want to load a .env file explicitly

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: SecretStr
    DATABASE_URL: PostgresDsn # Ensures the URL is a valid PostgreSQL DSN (for asyncpg)
    ADMIN_USER_IDS: List[int] = Field(default_factory=list)

    DEFAULT_CRYPTO_WALLET: Optional[str] = None
    DEFAULT_CRYPTO_NETWORK: Optional[str] = None
    
    REMINDER_DAYS_AHEAD: int = 3
    LOG_LEVEL: str = "INFO"

    @validator('ADMIN_USER_IDS', pre=True)
    def parse_admin_user_ids(cls, value: Optional[str]) -> List[int]:
        if isinstance(value, str):
            if not value.strip(): # Handle empty string
                return []
            try:
                return [int(user_id.strip()) for user_id in value.split(',') if user_id.strip()]
            except ValueError as e:
                raise ValueError(f"Invalid ADMIN_USER_IDS format. Must be a comma-separated list of integers. Error: {e}")
        elif value is None: # Handle case where env var is not set at all
            return []
        # If it's already a list (e.g., from direct instantiation for tests), return as is.
        # Pydantic usually handles this, but explicit check doesn't hurt.
        elif isinstance(value, list):
            return value
        raise TypeError("ADMIN_USER_IDS must be a string or list of integers.")


    @validator('LOG_LEVEL')
    def validate_log_level(cls, value: str) -> str:
        value_upper = value.upper()
        if value_upper not in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"]:
            raise ValueError(f"Invalid LOG_LEVEL: {value}. Must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET.")
        return value_upper

    class Config:
        # Attempt to load from .env file if variables are not set in the environment
        # The default behavior of pydantic-settings is to load from .env if python-dotenv is installed.
        # Explicitly setting env_file can ensure this.
        env_file = os.getenv("ENV_FILE", ".env") # Allow overriding .env file path via ENV_FILE var
        env_file_encoding = 'utf-8'
        extra = "ignore" # Ignore extra fields from .env or environment

# Create a single instance to be imported by other modules
try:
    settings = Settings()
except ValueError as e:
    # This will catch validation errors from Pydantic
    # For critical errors (like missing token/db_url), the app shouldn't run.
    # Logging here might be problematic if logger itself isn't configured yet.
    # So, print and exit is a robust way for critical config errors.
    print(f"CRITICAL CONFIGURATION ERROR: {e}")
    # You might want to log this to a fallback logger or just print.
    # In a containerized environment, the container should fail to start.
    exit(1) # Exit if essential settings are invalid or missing.

# Configure root logger based on settings
# This should be done once, early in the application lifecycle.
# Doing it here means that as soon as config.py is imported, logging is set up.
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), None)
if not isinstance(numeric_level, int):
    # Fallback in case LOG_LEVEL is somehow invalid despite validator (should not happen)
    logging.warning(f"Invalid LOG_LEVEL {settings.LOG_LEVEL}. Defaulting to INFO.")
    numeric_level = logging.INFO

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=numeric_level
)
# Test log message
# logging.info(f"Logger configured with level {settings.LOG_LEVEL}") # This will print if level is INFO/DEBUG
# logging.debug("This is a debug message from config.py") # This will only print if level is DEBUG
