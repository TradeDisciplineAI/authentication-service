"""Locust load test entrypoint for backend API.

Simulates realistic virtual user behavior:
1. Automatically provisions test-user accounts on Locust init (@events.init).
2. Assigns a unique account from the provisioned pool during initialization (on_start).
3. Authenticates ONCE per virtual user session without retry loops or respawn storms.
4. Performs periodic profile queries, token refreshes, and health checks ONLY when authenticated.
5. Logs out cleanly at session teardown (on_stop).
6. Automatically generates native Locust HTML & CSV reports on test completion (@events.test_stop).
"""

import logging
from typing import Any

from locust import HttpUser, between, events, task

from tests.performance.config import config
from tests.performance.provisioner import provision_test_users
from tests.performance.reporter import generate_native_reports
from tests.performance.tasks.auth_tasks import (
    get_user_profile,
    login_user,
    logout_user,
    refresh_token,
)

logger = logging.getLogger(__name__)


@events.init.add_listener
def on_locust_init(environment: Any, **kwargs: Any) -> None:
    """Automatically provision required test user accounts when Locust initializes."""
    if config.AUTO_PROVISION:
        logger.info("Initializing automatic test-user provisioning...")
        accounts = provision_test_users()
        config.set_user_pool(accounts)


@events.test_stop.add_listener
def on_test_stop(environment: Any, **kwargs: Any) -> None:
    """Automatically generate native Locust reports when load test completes."""
    generate_native_reports(environment)


class BackendUser(HttpUser):
    """Locust Virtual User simulating backend interaction patterns."""

    host = config.BASE_URL
    wait_time = between(config.MIN_WAIT, config.MAX_WAIT)

    username: str | None = None
    password: str | None = None
    access_token: str | None = None

    def on_start(self) -> None:
        """Select unique account and authenticate virtual user session on spawn."""
        account = config.get_next_account()
        self.username = account["username"]
        self.password = account["password"]

        # Authenticate ONCE per virtual user session without retry loops
        self.access_token = login_user(
            client=self.client,
            username=self.username,
            password=self.password,
        )

        if self.access_token:
            logger.info("Virtual user '%s' successfully authenticated.", self.username)
        else:
            logger.warning(
                "Virtual user '%s' authentication failed/rate-limited. Session unauthenticated.",
                self.username,
            )

    def on_stop(self) -> None:
        """Teardown user session when virtual user stops."""
        if self.access_token:
            logout_user(client=self.client)
            self.access_token = None

    @task(3)
    def task_get_profile(self) -> None:
        """Fetch user profile endpoint (/auth/me)."""
        if not self.access_token:
            return
        get_user_profile(client=self.client, access_token=self.access_token)

    @task(2)
    def task_refresh_token(self) -> None:
        """Exercise refresh token rotation (/auth/refresh)."""
        if not self.access_token:
            return
        new_token = refresh_token(client=self.client)
        if new_token:
            self.access_token = new_token

    @task(1)
    def task_health_check(self) -> None:
        """Query basic application health baseline (/health)."""
        with self.client.get(
            "/health", catch_response=True, name="/health"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(
                    f"Health check failed with status {response.status_code}"
                )
