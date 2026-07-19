"""Configuration module for Locust performance tests.

Supports auto-provisioned test accounts, user pools, and report generation settings.
"""

import json
import logging
import os
import random
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class PerformanceConfig:
    """Configuration settings for backend load testing."""

    # Target Host
    BASE_URL: str = os.getenv(
        "LOCUST_HOST", os.getenv("BASE_URL", "http://localhost:8000")
    )

    # Test User Provisioning & Credentials
    USER_PREFIX: str = os.getenv(
        "LOCUST_USER_PREFIX", os.getenv("USER_PREFIX", "loadtest")
    )
    LOAD_TEST_PASSWORD: str = os.getenv(
        "LOAD_TEST_PASSWORD",
        os.getenv("TEST_PASSWORD", "Password123!"),
    )
    TEST_USERNAME: str = os.getenv("TEST_USERNAME", "testuser@example.com")
    TEST_PASSWORD: str = os.getenv("TEST_PASSWORD", LOAD_TEST_PASSWORD)

    # Auto-Provisioning Toggle
    AUTO_PROVISION: bool = (
        os.getenv("LOCUST_AUTO_PROVISION", os.getenv("AUTO_PROVISION", "true")).lower()
        != "false"
    )

    # User Pool File Location
    USER_POOL_FILE: str = os.getenv(
        "LOCUST_USER_POOL_FILE",
        os.getenv("USER_POOL_FILE", str(Path(__file__).parent / "users.json")),
    )

    # Cookie Settings
    COOKIE_NAME: str = os.getenv("COOKIE_NAME", "refresh_token")
    COOKIE_PATH: str = os.getenv("COOKIE_PATH", "/auth")

    # Load Simulation Parameters
    NUM_USERS: int = int(os.getenv("LOCUST_USERS", os.getenv("NUM_USERS", "20")))
    SPAWN_RATE: float = float(
        os.getenv("LOCUST_SPAWN_RATE", os.getenv("SPAWN_RATE", "2.0"))
    )

    # Request Pacing (in seconds)
    MIN_WAIT: float = float(os.getenv("LOCUST_MIN_WAIT", os.getenv("MIN_WAIT", "1.0")))
    MAX_WAIT: float = float(os.getenv("LOCUST_MAX_WAIT", os.getenv("MAX_WAIT", "3.0")))

    # Rate Limiting Backoff Parameters
    MAX_LOGIN_RETRIES: int = int(os.getenv("MAX_LOGIN_RETRIES", "1"))
    LOGIN_BACKOFF_SEC: float = float(os.getenv("LOGIN_BACKOFF_SEC", "2.0"))

    # Report Generation Settings
    REPORT_DIRECTORY: str = os.getenv(
        "LOCUST_REPORT_DIRECTORY",
        os.getenv("REPORT_DIRECTORY", "reports/authentication"),
    )
    REPORT_FILENAME_PREFIX: str = os.getenv(
        "LOCUST_REPORT_FILENAME_PREFIX",
        os.getenv("REPORT_FILENAME_PREFIX", "auth-report"),
    )
    ENABLE_TIMESTAMPED_REPORTS: bool = (
        os.getenv(
            "LOCUST_ENABLE_TIMESTAMPED_REPORTS",
            os.getenv("ENABLE_TIMESTAMPED_REPORTS", "true"),
        ).lower()
        != "false"
    )

    def __init__(self) -> None:
        self._user_pool: list[dict[str, str]] | None = None
        self._account_index: int = 0
        self._lock = threading.Lock()

        # Log security warning if default load test password is used
        if not os.getenv("LOAD_TEST_PASSWORD") and not os.getenv("TEST_PASSWORD"):
            logger.warning(
                "LOAD_TEST_PASSWORD environment variable is not explicitly set. "
                "Using default test password for local load testing."
            )

    def _validate_pool_entries(
        self, entries: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Validate JSON structure, required fields, and deduplicate accounts by username."""
        valid_pool: list[dict[str, str]] = []
        seen_usernames: set[str] = set()

        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                logger.warning(
                    "Ignoring invalid non-dict entry at index %d in user pool", idx
                )
                continue
            username = entry.get("username")
            password = entry.get("password")
            if (
                not username
                or not password
                or not isinstance(username, str)
                or not isinstance(password, str)
            ):
                logger.warning(
                    "Ignoring user pool entry at index %d missing username or password",
                    idx,
                )
                continue
            if username in seen_usernames:
                logger.warning(
                    "Ignoring duplicate username '%s' in user pool at index %d",
                    username,
                    idx,
                )
                continue
            seen_usernames.add(username)
            valid_pool.append(entry)

        return valid_pool

    def load_user_pool(self) -> list[dict[str, str]]:
        """Load pool of test accounts from JSON file, environment, or provisioner.

        Returns:
            List of account dictionaries containing 'username' and 'password'.
        """
        if self._user_pool is not None:
            return self._user_pool

        # 1. Try inline JSON env var
        pool_json_env = os.getenv("LOCUST_USER_POOL_JSON")
        if pool_json_env:
            try:
                data = json.loads(pool_json_env)
                if isinstance(data, list):
                    valid = self._validate_pool_entries(data)
                    if valid:
                        self._user_pool = valid
                        logger.info(
                            "Loaded %d valid users from LOCUST_USER_POOL_JSON",
                            len(valid),
                        )
                        return self._user_pool
            except Exception as exc:
                logger.warning("Failed to parse LOCUST_USER_POOL_JSON: %s", exc)

        # 2. Try user pool JSON file
        pool_file = Path(self.USER_POOL_FILE)
        if pool_file.exists():
            try:
                with pool_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    valid = self._validate_pool_entries(data)
                    if len(valid) >= self.NUM_USERS:
                        self._user_pool = valid
                        logger.info(
                            "Loaded %d valid users from pool file: %s",
                            len(valid),
                            self.USER_POOL_FILE,
                        )
                        return self._user_pool
                    elif not self.AUTO_PROVISION:
                        raise ValueError(
                            f"Configured benchmark requires {self.NUM_USERS} virtual users, "
                            f"but user pool file contains only {len(valid)} valid account(s). "
                            "Auto-provisioning is disabled (LOCUST_AUTO_PROVISION=false)."
                        )
            except ValueError:
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to read user pool file %s: %s", self.USER_POOL_FILE, exc
                )

        if not self.AUTO_PROVISION:
            raise ValueError(
                f"Configured benchmark requires {self.NUM_USERS} virtual users, "
                f"but no valid user pool file was found at '{self.USER_POOL_FILE}' "
                "and auto-provisioning is disabled (LOCUST_AUTO_PROVISION=false)."
            )

        # 3. Fallback to single test user credentials
        logger.info(
            "Using fallback credentials for test user: %s",
            self.TEST_USERNAME,
        )
        self._user_pool = [
            {
                "username": self.TEST_USERNAME,
                "password": self.TEST_PASSWORD,
            }
        ]
        return self._user_pool

    def set_user_pool(self, pool: list[dict[str, str]]) -> None:
        """Explicitly set the user pool in memory after validation."""
        valid = self._validate_pool_entries(pool)
        if not valid:
            raise ValueError("Cannot set empty or invalid user pool.")
        self._user_pool = valid
        self._account_index = 0

    def get_next_account(self) -> dict[str, str]:
        """Select accounts sequentially using round-robin distribution.

        Returns:
            Dictionary with 'username' and 'password'.
        """
        pool = self.load_user_pool()
        with self._lock:
            account = pool[self._account_index % len(pool)]
            self._account_index += 1
            return account

    def get_random_account(self) -> dict[str, str]:
        """Randomly select one test account from the pool.

        Returns:
            Dictionary with 'username' and 'password'.
        """
        pool = self.load_user_pool()
        return random.choice(pool)  # noqa: S311


config = PerformanceConfig()
