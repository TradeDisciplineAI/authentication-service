# ------------------ Subscriptions Router Feature -----------------------
"""
FastAPI REST router for subscription and payment gateway endpoints.
Exposes routes to retrieve subscription plans, create Razorpay orders,
verify HMAC-SHA256 signatures, upgrade user tiers, and retrieve active subscription status.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.dependencies import get_current_user, get_db
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.subscription import (
    CreateOrderRequest,
    CreateOrderResponse,
    SubscriptionPlanResponse,
    UserSubscriptionResponse,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from ai_trading_discipline_copilot.services.razorpay_service import RazorpayService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["Razorpay Subscriptions"])


# ------------------ Get Subscription Plans Endpoint -----------------------
@router.get(
    "/plans",
    response_model=list[SubscriptionPlanResponse],
    status_code=status.HTTP_200_OK,
)
async def get_subscription_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SubscriptionPlanResponse]:
    """
    Public endpoint retrieving available subscription plans (FREE with 5 portfolios, PRO with 15 portfolios).
    Both plans include full access to all AI Agents (Agents 1-6).
    """
    plans = await RazorpayService.get_or_seed_plans(db)
    return [SubscriptionPlanResponse.model_validate(p) for p in plans]


# ------------------ Create Payment Order Endpoint -----------------------
@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_order(
    request: CreateOrderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreateOrderResponse:
    """
    Authenticated endpoint creating a new Razorpay payment order for the specified plan ID.
    Generates a unique order ID and receipt for frontend Razorpay checkout initialization.
    """
    order_data = await RazorpayService.create_order(
        db=db,
        user_id=current_user.id,
        plan_id=request.plan_id,
    )
    return CreateOrderResponse(**order_data)


# ------------------ Verify Payment Signature Endpoint -----------------------
@router.post(
    "/verify-payment",
    response_model=VerifyPaymentResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_payment_signature(
    request: VerifyPaymentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VerifyPaymentResponse:
    """
    Authenticated endpoint validating Razorpay payment signature via HMAC-SHA256 constant-time check.
    On valid verification, updates payment order status to PAID, logs audit transaction,
    upgrades user's subscription_tier to PRO, and activates 30-day subscription period.
    """
    result = await RazorpayService.verify_and_activate_payment(
        db=db,
        user_id=current_user.id,
        razorpay_order_id=request.razorpay_order_id,
        razorpay_payment_id=request.razorpay_payment_id,
        razorpay_signature=request.razorpay_signature,
    )
    return VerifyPaymentResponse(**result)


# ------------------ Get My Active Subscription Endpoint -----------------------
@router.get(
    "/my-subscription",
    response_model=UserSubscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_my_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserSubscriptionResponse:
    """
    Authenticated endpoint retrieving current user's active subscription tier, plan name,
    portfolio addition limits, and subscription period expiration dates.
    """
    sub = await RazorpayService.get_user_subscription(db, current_user.id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User subscription not found",
        )
    return UserSubscriptionResponse(**sub)
