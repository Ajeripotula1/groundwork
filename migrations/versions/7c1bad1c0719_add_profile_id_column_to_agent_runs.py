"""add profile_id column to agent_runs

Revision ID: 7c1bad1c0719
Revises: 3cc32e5342bd
Create Date: 2026-09-19 14:34:22.673778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1bad1c0719'
down_revision: Union[str, Sequence[str], None] = '3cc32e5342bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_runs', sa.Column('profile_id', sa.Integer(), nullable=True))
    # Named explicitly - Alembic autogenerate rendered this as an unnamed
    # constraint (op.create_foreign_key(None, ...)), which downgrade()
    # can't reference. This project has no naming convention configured
    # (see MetaData in jobsentinel.db.models), so every FK needs an
    # explicit name to stay reversible.
    op.create_foreign_key(
        'fk_agent_runs_profile_id_profiles', 'agent_runs', 'profiles', ['profile_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_agent_runs_profile_id_profiles', 'agent_runs', type_='foreignkey')
    op.drop_column('agent_runs', 'profile_id')
