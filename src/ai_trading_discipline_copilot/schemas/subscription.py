from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ------------------ Subscription Plan Response Schema -----------------------
class SubscriptionPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    amount: int
    currency: str
    billing_interval: str
    max_portfolios: int


# ------------------ Create Payment Order Schemas -----------------------
class CreateOrderRequest(BaseModel):
    plan_id: UUID


class CreateOrderResponse(BaseModel):
    order_id: UUID
    razorpay_order_id: str
    amount: int
    currency: str
    key_id: str
    plan_name: str
    receipt: str


# ------------------ Verify Payment Signature Schemas -----------------------
class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class VerifyPaymentResponse(BaseModel):
    status: str
    message: str
    subscription_tier: str
    current_period_end: datetime


# ------------------ User Subscription Response Schema -----------------------
class UserSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    plan_name: str
    subscription_tier: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
