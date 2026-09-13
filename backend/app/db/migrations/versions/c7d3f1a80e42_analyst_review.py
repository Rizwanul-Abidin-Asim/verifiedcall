"""analyst review

A human can release or block a payment the agent has already decided on. The three
columns sit alongside `outcome` rather than replacing it: the agent's decision stays on
the record, and what a person did about it is a separate fact. "The agent held this and
an analyst released it, because the customer called back and confirmed" is the sentence
a fraud team actually needs, and it cannot be reconstructed from a single overwritten
field.

All nullable — every decision taken before this existed genuinely has no reviewer, and
null says that honestly.

Revision ID: c7d3f1a80e42
Revises: a1c4e9f20b31
Create Date: 2026-09-13 00:20:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c7d3f1a80e42'
down_revision: str | None = 'a1c4e9f20b31'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('decisions', sa.Column(
        'analyst_action',
        sa.Enum('released', 'blocked', name='analystaction', native_enum=False,
                create_constraint=True, length=16),
        nullable=True))
    op.add_column('decisions', sa.Column('analyst_reason', sa.Text(), nullable=True))
    op.add_column('decisions', sa.Column(
        'analyst_reviewed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.drop_column('analyst_reviewed_at')
        batch_op.drop_column('analyst_reason')
        batch_op.drop_column('analyst_action')
