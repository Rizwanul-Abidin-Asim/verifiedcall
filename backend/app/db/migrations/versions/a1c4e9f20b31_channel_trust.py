"""channel trust routing

Two changes, both driven by the same idea: the question "can we reach this customer?"
stopped having an assumed answer.

1. decisions.channel_assessment — which of voice, app push and SMS the network says are
   still trustworthy for this customer at this moment, and which signal closed the ones
   that are not. Nullable: decisions taken before this existed genuinely have no answer,
   and recording a blank is more honest than backfilling a guess.

2. voice_calls.channel gains 'app_push' and 'sms'. The column already carried a CHECK
   constraint (enum_column uses create_constraint=True deliberately), so widening the
   enum means rebuilding the constraint rather than just writing new values. SQLite
   cannot alter a constraint in place, hence batch mode.

Revision ID: a1c4e9f20b31
Revises: 73f408e50884
Create Date: 2026-09-12 15:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c4e9f20b31'
down_revision: str | None = '73f408e50884'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ('phone', 'web')
_NEW = ('phone', 'web', 'app_push', 'sms')


def _channel_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name='voicechannel', native_enum=False,
                   create_constraint=True, length=8)


def upgrade() -> None:
    op.add_column('decisions', sa.Column('channel_assessment', sa.JSON(), nullable=True))

    # The constraint has to be named for SQLite to find it on the way through the batch
    # rebuild; enum_column's create_constraint generates 'voicechannel'.
    with op.batch_alter_table('voice_calls', schema=None) as batch_op:
        batch_op.alter_column(
            'channel',
            existing_type=_channel_enum(_OLD),
            type_=_channel_enum(_NEW),
            existing_nullable=False,
            existing_server_default='phone',
        )


def downgrade() -> None:
    # Any row already using a new channel would violate the narrowed constraint, so it
    # is mapped back to the closest old value rather than letting the downgrade fail
    # halfway. 'web' because, like app push, it reached the customer without a carrier.
    op.execute("UPDATE voice_calls SET channel = 'web' "
               "WHERE channel IN ('app_push', 'sms')")

    with op.batch_alter_table('voice_calls', schema=None) as batch_op:
        batch_op.alter_column(
            'channel',
            existing_type=_channel_enum(_NEW),
            type_=_channel_enum(_OLD),
            existing_nullable=False,
            existing_server_default='phone',
        )

    op.drop_column('decisions', 'channel_assessment')
