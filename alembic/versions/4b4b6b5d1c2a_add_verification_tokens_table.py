"""add verification tokens table

Revision ID: 4b4b6b5d1c2a
Revises: 11781e907181
Create Date: 2026-03-17 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b4b6b5d1c2a"
down_revision: str | Sequence[str] | None = "11781e907181"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_verification_tokens_id"),
        "verification_tokens",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_tokens_token"),
        "verification_tokens",
        ["token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_verification_tokens_token"), table_name="verification_tokens"
    )
    op.drop_index(op.f("ix_verification_tokens_id"), table_name="verification_tokens")
    op.drop_table("verification_tokens")
