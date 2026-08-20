from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.models.subscription_models import (
    OrderStatus,
    PaymentOrder,
    PaymentTransaction,
    SubscriptionPlan,
    SubscriptionStatus,
    UserSubscription,
)
from ai_trading_discipline_copilot.models.user import User

settings = get_settings()
logger = logging.getLogger(__name__)


# ------------------ Razorpay Service Feature -----------------------
class RazorpayService:

    # ------------------ Get Or Seed Subscription Plans -----------------------
    @staticmethod
    async def get_or_seed_plans(db: AsyncSession) -> list[SubscriptionPlan]:
        result = await db.execute(select(SubscriptionPlan))
        plans = list(result.scalars().all())

        if not plans:
            default_plans = [
                SubscriptionPlan(
                    id=uuid.uuid4(),
                    name="FREE",
                    description="Free plan with 5 portfolio limit and full access to all AI Agents (Agents 1-6)",
                    amount=0,
                    currency="INR",
                    billing_interval="monthly",
                    max_portfolios=5,
                ),
                SubscriptionPlan(
                    id=uuid.uuid4(),
                    name="PRO",
                    description="Pro plan with 15 portfolio limit and full access to all AI Agents (Agents 1-6)",
                    amount=199900,
                    currency="INR",
                    billing_interval="monthly",
                    max_portfolios=15,
                ),
            ]
            db.add_all(default_plans)
            await db.commit()

            result = await db.execute(select(SubscriptionPlan))
            plans = list(result.scalars().all())

        return plans

    # ------------------ Create Razorpay Payment Order -----------------------
    @staticmethod
    async def create_order(
        db: AsyncSession,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
    ) -> dict[str, Any]:
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
        )
        plan = plan_result.scalar_one_or_none()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription plan not found.",
            )

        receipt = f"rcpt_{uuid.uuid4().hex[:12]}"
        razorpay_key_id = settings.razorpay_key_id
        razorpay_order_id = f"order_{uuid.uuid4().hex[:14]}"

        order = PaymentOrder(
            id=uuid.uuid4(),
            user_id=user_id,
            plan_id=plan.id,
            razorpay_order_id=razorpay_order_id,
            amount=plan.amount,
            currency=plan.currency,
            status=OrderStatus.CREATED,
            receipt=receipt,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)

        return {
            "order_id": order.id,
            "razorpay_order_id": order.razorpay_order_id,
            "amount": order.amount,
            "currency": order.currency,
            "key_id": razorpay_key_id,
            "plan_name": plan.name,
            "receipt": receipt,
        }

    # ------------------ Verify HMAC SHA256 Signature -----------------------
    @staticmethod
    def verify_hmac_signature(order_id: str, payment_id: str, signature: str) -> bool:
        secret = settings.razorpay_key_secret.get_secret_value()
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        expected_sig = hmac.new(
            secret.encode("utf-8"),
            msg,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, signature)

    # ------------------ Verify And Activate Subscription -----------------------
    @staticmethod
    async def verify_and_activate_payment(
        db: AsyncSession,
        user_id: uuid.UUID,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        if not RazorpayService.verify_hmac_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        ):
            logger.warning(
                "Invalid payment signature attempt for order %s from user %s",
                razorpay_order_id,
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment signature. Payment verification failed.",
            )

        order_result = await db.execute(
            select(PaymentOrder).where(
                PaymentOrder.razorpay_order_id == razorpay_order_id
            )
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment order not found.",
            )

        if order.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this payment order.",
            )

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == order.plan_id)
        )
        plan = plan_result.scalar_one_or_none()
        plan_name = plan.name if plan else "PRO"

        order.status = OrderStatus.PAID
        db.add(order)

        transaction = PaymentTransaction(
            id=uuid.uuid4(),
            order_id=order.id,
            user_id=user_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            amount=order.amount,
            status="SUCCESS",
        )
        db.add(transaction)

        user.subscription_tier = plan_name
        db.add(user)

        now = datetime.now(UTC)
        period_end = now + timedelta(days=30)

        sub_result = await db.execute(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        )
        subscription = sub_result.scalar_one_or_none()

        if subscription:
            subscription.plan_id = order.plan_id
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.current_period_start = now
            subscription.current_period_end = period_end
        else:
            subscription = UserSubscription(
                id=uuid.uuid4(),
                user_id=user_id,
                plan_id=order.plan_id,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=now,
                current_period_end=period_end,
            )
        db.add(subscription)

        await db.commit()

        return {
            "status": "SUCCESS",
            "message": f"Payment verified successfully! Subscribed to {plan_name} plan.",
            "subscription_tier": user.subscription_tier,
            "current_period_end": period_end,
        }

    # ------------------ Get User Active Subscription Details -----------------------
    @staticmethod
    async def get_user_subscription(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        sub_result = await db.execute(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        )
        subscription = sub_result.scalar_one_or_none()

        if not subscription:
            return {
                "user_id": user_id,
                "subscription_tier": user.subscription_tier,
                "status": "FREE",
                "plan_name": "FREE",
                "current_period_start": user.created_at,
                "current_period_end": user.created_at + timedelta(days=3650),
            }

        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        return {
            "id": subscription.id,
            "user_id": user_id,
            "plan_name": plan.name if plan else user.subscription_tier,
            "subscription_tier": user.subscription_tier,
            "status": subscription.status.value,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
        }
