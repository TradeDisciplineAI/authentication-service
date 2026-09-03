import hashlib
import hmac
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.security import create_access_token
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.services.razorpay_service import RazorpayService

settings = get_settings()


# ------------------ Authenticated AsyncClient Helper -----------------------
async def get_authenticated_client(client: AsyncClient, user: User) -> AsyncClient:
    token, _ = create_access_token(user_id=str(user.id))
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ------------------ Sample Test User Fixture -----------------------
@pytest.fixture
async def sample_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"sub_user_{uuid.uuid4().hex[:6]}",
        email=f"sub_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_password_placeholder",
        is_active=True,
        is_verified=True,
        subscription_tier="FREE",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ------------------ Get Subscription Plans Test -----------------------
@pytest.mark.asyncio
async def test_get_subscription_plans(client: AsyncClient, db_session: AsyncSession):
    response = await client.get("/subscriptions/plans")
    assert response.status_code == 200
    plans = response.json()
    plan_names = [p["name"] for p in plans]
    assert "FREE" in plan_names
    assert "PRO" in plan_names
    assert "PREMIUM" not in plan_names

    free_plan = next(p for p in plans if p["name"] == "FREE")
    pro_plan = next(p for p in plans if p["name"] == "PRO")
    assert free_plan["max_portfolios"] == 5
    assert pro_plan["max_portfolios"] == 15


# ------------------ Create Payment Order Test -----------------------
@pytest.mark.asyncio
async def test_create_payment_order(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_user: User,
):
    plans = await RazorpayService.get_or_seed_plans(db_session)
    pro_plan = next(p for p in plans if p.name == "PRO")

    unauth_resp = await client.post(
        "/subscriptions/create-order",
        json={"plan_id": str(pro_plan.id)},
    )
    assert unauth_resp.status_code == 401

    auth_client = await get_authenticated_client(client, sample_user)
    response = await auth_client.post(
        "/subscriptions/create-order",
        json={"plan_id": str(pro_plan.id)},
    )
    assert response.status_code == 201
    data = response.json()
    assert "order_id" in data
    assert "razorpay_order_id" in data
    assert data["amount"] == pro_plan.amount
    assert data["plan_name"] == "PRO"


# ------------------ Verify Valid Payment Signature Test -----------------------
@pytest.mark.asyncio
async def test_verify_valid_payment_signature(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_user: User,
):
    plans = await RazorpayService.get_or_seed_plans(db_session)
    pro_plan = next(p for p in plans if p.name == "PRO")

    order_data = await RazorpayService.create_order(
        db=db_session,
        user_id=sample_user.id,
        plan_id=pro_plan.id,
    )
    rzp_order_id = order_data["razorpay_order_id"]
    rzp_payment_id = f"pay_{uuid.uuid4().hex[:12]}"

    secret = settings.razorpay_key_secret.get_secret_value()
    msg = f"{rzp_order_id}|{rzp_payment_id}".encode()
    valid_signature = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    auth_client = await get_authenticated_client(client, sample_user)

    verify_resp = await auth_client.post(
        "/subscriptions/verify-payment",
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_payment_id,
            "razorpay_signature": valid_signature,
        },
    )
    assert verify_resp.status_code == 200
    res_data = verify_resp.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["subscription_tier"] == "PRO"

    sub_resp = await auth_client.get("/subscriptions/my-subscription")
    assert sub_resp.status_code == 200
    sub_data = sub_resp.json()
    assert sub_data["subscription_tier"] == "PRO"
    assert sub_data["status"] == "ACTIVE"


# ------------------ Reject Invalid Payment Signature Test -----------------------
@pytest.mark.asyncio
async def test_reject_invalid_payment_signature(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_user: User,
):
    plans = await RazorpayService.get_or_seed_plans(db_session)
    pro_plan = next(p for p in plans if p.name == "PRO")

    order_data = await RazorpayService.create_order(
        db=db_session,
        user_id=sample_user.id,
        plan_id=pro_plan.id,
    )
    rzp_order_id = order_data["razorpay_order_id"]
    rzp_payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    fake_signature = "fake_invalid_hmac_signature_123456789"

    auth_client = await get_authenticated_client(client, sample_user)
    verify_resp = await auth_client.post(
        "/subscriptions/verify-payment",
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_payment_id,
            "razorpay_signature": fake_signature,
        },
    )
    assert verify_resp.status_code == 400
    assert "Invalid payment signature" in verify_resp.json()["detail"]
