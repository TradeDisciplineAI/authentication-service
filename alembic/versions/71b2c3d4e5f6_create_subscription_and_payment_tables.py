"""create_subscription_and_payment_tables

Revision ID: 71b2c3d4e5f6
Revises: fb747c9eaa7a
Create Date: 2026-08-31 11:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "71b2c3d4e5f6"
down_revision: str | None = "fb747c9eaa7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------ Create Enums -----------------------
    subscription_status_enum = postgresql.ENUM(
        "ACTIVE", "CANCELLED", "EXPIRED", "PENDING",
        name="subscription_status",
        schema="authentication",
        create_type=False,
    )
    subscription_status_enum.create(op.get_bind(), checkfirst=True)

    order_status_enum = postgresql.ENUM(
        "CREATED", "PAID", "FAILED",
        name="order_status",
        schema="authentication",
        create_type=False,
    )
    order_status_enum.create(op.get_bind(), checkfirst=True)

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names(schema="authentication")

    # ------------------ Subscription Plans Table -----------------------
    if "subscription_plans" not in existing_tables:
        op.create_table(
            "subscription_plans",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(50), unique=True, nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(10), server_default="INR", nullable=False),
            sa.Column("billing_interval", sa.String(20), server_default="monthly", nullable=False),
            sa.Column("max_portfolios", sa.Integer(), server_default="5", nullable=False),
            sa.Column("razorpay_plan_id", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema="authentication",
        )

    # ------------------ User Subscriptions Table -----------------------
    if "user_subscriptions" not in existing_tables:
        op.create_table(
            "user_subscriptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authentication.users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "plan_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authentication.subscription_plans.id"),
                nullable=False,
            ),
            sa.Column("razorpay_subscription_id", sa.String(255), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "ACTIVE", "CANCELLED", "EXPIRED", "PENDING",
                    name="subscription_status",
                    schema="authentication",
                    create_type=False,
                ),
                server_default="PENDING",
                nullable=False,
            ),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema="authentication",
        )
        op.create_index(
            "ix_authentication_user_subscriptions_user_id",
            "user_subscriptions",
            ["user_id"],
            schema="authentication",
        )
        op.create_index(
            "ix_authentication_user_subscriptions_razorpay_subscription_id",
            "user_subscriptions",
            ["razorpay_subscription_id"],
            schema="authentication",
        )

    # ------------------ Payment Orders Table -----------------------
    if "payment_orders" not in existing_tables:
        op.create_table(
            "payment_orders",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authentication.users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "plan_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authentication.subscription_plans.id"),
                nullable=False,
            ),
            sa.Column("razorpay_order_id", sa.String(255), unique=True, nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(10), server_default="INR", nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "CREATED", "PAID", "FAILED",
                    name="order_status",
                    schema="authentication",
                    create_type=False,
                ),
                server_default="CREATED",
                nullable=False,
            ),
            sa.Column("receipt", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema="authentication",
        )
        op.create_index(
            "ix_authentication_payment_orders_user_id",
            "payment_orders",
            ["user_id"],
            schema="authentication",
        )
        op.create_index(
            "ix_authentication_payment_orders_razorpay_order_id",
            "payment_orders",
            ["razorpay_order_id"],
            schema="authentication",
        )

    # ------------------ Payment Transactions Table -----------------------
    if "payment_transactions" not in existing_tables:
        op.create_table(
            "payment_transactions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "order_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authentication.payment_orders.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authentication.users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("razorpay_payment_id", sa.String(255), unique=True, nullable=False),
            sa.Column("razorpay_signature", sa.String(255), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(50), server_default="SUCCESS", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema="authentication",
        )
        op.create_index(
            "ix_authentication_payment_transactions_user_id",
            "payment_transactions",
            ["user_id"],
            schema="authentication",
        )
        op.create_index(
            "ix_authentication_payment_transactions_razorpay_payment_id",
            "payment_transactions",
            ["razorpay_payment_id"],
            schema="authentication",
        )


def downgrade() -> None:
    op.drop_table("payment_transactions", schema="authentication")
    op.drop_table("payment_orders", schema="authentication")
    op.drop_table("user_subscriptions", schema="authentication")
    op.drop_table("subscription_plans", schema="authentication")
    op.execute("DROP TYPE IF EXISTS authentication.order_status CASCADE")
    op.execute("DROP TYPE IF EXISTS authentication.subscription_status CASCADE")
