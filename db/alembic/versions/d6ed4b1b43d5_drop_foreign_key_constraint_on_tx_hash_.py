"""Drop foreign key constraint on tx hash on ethereum_labels table

Revision ID: d6ed4b1b43d5
Revises: 72f1ad512b2e
Create Date: 2021-09-23 21:02:46.577682

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d6ed4b1b43d5"
down_revision = "72f1ad512b2e"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(
        "fk_ethereum_labels_transaction_hash_ethereum_transactions",
        "ethereum_labels",
        type_="foreignkey",
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_foreign_key(
        "fk_ethereum_labels_transaction_hash_ethereum_transactions",
        "ethereum_labels",
        "ethereum_transactions",
        ["transaction_hash"],
        ["hash"],
        ondelete="CASCADE",
    )
    # ### end Alembic commands ###
