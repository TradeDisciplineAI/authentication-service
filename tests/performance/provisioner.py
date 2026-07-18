"""Automatic test-user provisioning module for Locust performance tests.

Delegates user creation to application UserService and UserCreate schema,
ensuring application business logic and validation remain the single source of truth.

To avoid event loop conflicts between gevent (Locust) and asyncio (asyncpg),
provisioning is executed in an isolated process context when invoked from Locust.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

from sqlalchemy import select

from ai_trading_discipline_copilot.core.database import AsyncSessionFactory
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.user import UserCreate
from ai_trading_discipline_copilot.services.user_service import UserService
from tests.performance.config import config

logger = logging.getLogger(__name__)


def generate_account_list(
    num_users: int,
    prefix: str,
    password: str,
) -> list[dict[str, str]]:
    """Generate deterministic list of test account dictionaries.

    Args:
        num_users: Target number of accounts.
        prefix: Email and username prefix (e.g., 'loadtest').
        password: Password for all test accounts.

    Returns:
        List of dicts with 'username', 'email', and 'password'.
    """
    accounts = []
    for i in range(1, num_users + 1):
        email = f"{prefix}-{i:05d}@example.com"
        username = f"{prefix}_{i:05d}"
        accounts.append(
            {
                "username": username,
                "email": email,
                "password": password,
            }
        )
    return accounts


async def provision_db_accounts(
    target_accounts: list[dict[str, str]],
    prefix: str,
) -> list[dict[str, str]]:
    """Provision missing test accounts via application UserService.

    Args:
        target_accounts: List of desired account dicts.
        prefix: Account email prefix filter.

    Returns:
        List of all verified account dicts present in the database.
    """
    try:
        async with AsyncSessionFactory() as db:
            # Query existing loadtest emails in database
            result = await db.execute(
                select(User.email).where(User.email.like(f"{prefix}-%"))
            )
            existing_emails = set(result.scalars().all())

            missing_accounts = [
                acc for acc in target_accounts if acc["email"] not in existing_emails
            ]

            if not missing_accounts:
                logger.info(
                    "All %d performance test accounts already exist in DB.",
                    len(target_accounts),
                )
                return target_accounts

            logger.info(
                "Provisioning %d missing performance test accounts via UserService...",
                len(missing_accounts),
            )

            for acc in missing_accounts:
                # 1. Validate through application schema
                user_data = UserCreate(
                    username=acc["username"],
                    email=acc["email"],
                    password=acc["password"],
                )
                # 2. Delegate creation to UserService (single source of truth)
                user = await UserService.register_user(db, user_data)

                # 3. Ensure test account is verified for load testing login
                if not user.is_verified:
                    user.is_verified = True
                    await db.commit()

            logger.info(
                "Successfully provisioned %d test users via UserService.",
                len(missing_accounts),
            )
            return target_accounts

    except Exception as exc:
        tb_str = traceback.format_exc()
        logger.error(
            "Provisioning via UserService failed\n"
            "Exception Type: %s\n"
            "Exception: %s\n"
            "Traceback:\n%s",
            type(exc).__name__,
            exc,
            tb_str,
        )
        raise exc


def save_user_pool_file(accounts: list[dict[str, str]], file_path: str) -> None:
    """Save provisioned user pool to a JSON file.

    Args:
        accounts: List of account dicts.
        file_path: Target JSON file path.
    """
    try:
        pool_data = [
            {
                "username": acc["username"],
                "password": acc["password"],
                "email": acc["email"],
            }
            for acc in accounts
        ]
        out_path = Path(file_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(pool_data, f, indent=2)
        logger.info(
            "Saved %d test accounts to user pool file: %s", len(accounts), file_path
        )
    except Exception as exc:
        logger.warning("Failed to save user pool file %s: %s", file_path, exc)


def _run_standalone_provisioner() -> list[dict[str, str]]:
    """Direct standalone provisioner execution in unpatched asyncio process."""
    target_count = config.NUM_USERS
    prefix = config.USER_PREFIX
    password = config.LOAD_TEST_PASSWORD

    target_accounts = generate_account_list(target_count, prefix, password)
    accounts = asyncio.run(provision_db_accounts(target_accounts, prefix))
    save_user_pool_file(accounts, config.USER_POOL_FILE)
    return accounts


def provision_test_users() -> list[dict[str, str]]:
    """Provision performance test accounts.

    If executed inside a gevent environment (e.g. Locust process), spawns an unpatched
    clean process to execute DB provisioning without gevent/asyncio socket conflicts.

    Returns:
        List of provisioned account dictionaries.
    """
    if not config.AUTO_PROVISION:
        logger.info("Auto-provisioning is disabled (LOCUST_AUTO_PROVISION=false).")
        return config.load_user_pool()

    # Check if running under gevent monkey-patching
    is_gevent = "gevent" in sys.modules

    if is_gevent:
        logger.info("Detected gevent runtime. Spawning process to run provisioner...")
        env = os.environ.copy()
        try:
            res = subprocess.run(
                [sys.executable, "-m", "tests.performance.provisioner"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info("Subprocess provisioning completed cleanly:\n%s", res.stdout)
            return config.load_user_pool()
        except subprocess.CalledProcessError as cpe:
            tb_str = traceback.format_exc()
            logger.error(
                "Provisioning via UserService failed in subprocess\n"
                "Exception Type: %s\n"
                "Exception: %s\n"
                "Subprocess Output:\n%s\n"
                "Subprocess Error:\n%s\n"
                "Traceback:\n%s",
                type(cpe).__name__,
                cpe,
                cpe.stdout,
                cpe.stderr,
                tb_str,
            )
            raise RuntimeError(
                f"Provisioning via UserService failed: {cpe.stderr}"
            ) from cpe
    else:
        return _run_standalone_provisioner()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _run_standalone_provisioner()
