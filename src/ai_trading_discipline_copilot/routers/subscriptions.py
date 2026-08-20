import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
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


@router.get(
    "/plans",
    response_model=list[SubscriptionPlanResponse],
    status_code=status.HTTP_200_OK,
)
async def get_subscription_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retrieves available subscription plans (PRO, PREMIUM)."""
    plans = await RazorpayService.get_or_seed_plans(db)
    return plans


@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_order(
    request: CreateOrderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Creates a Razorpay payment order for the requested subscription plan."""
    order_data = await RazorpayService.create_order(
        db=db,
        user_id=current_user.id,
        plan_id=request.plan_id,
    )
    return order_data


@router.post(
    "/verify-payment",
    response_model=VerifyPaymentResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_payment_signature(
    request: VerifyPaymentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verifies Razorpay payment signature (HMAC-SHA256), upgrades user tier & activates subscription."""
    result = await RazorpayService.verify_and_activate_payment(
        db=db,
        user_id=current_user.id,
        razorpay_order_id=request.razorpay_order_id,
        razorpay_payment_id=request.razorpay_payment_id,
        razorpay_signature=request.razorpay_signature,
    )
    return result


@router.get(
    "/my-subscription",
    response_model=UserSubscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_my_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retrieves current user's subscription details."""
    sub = await RazorpayService.get_user_subscription(db, current_user.id)
    return sub
