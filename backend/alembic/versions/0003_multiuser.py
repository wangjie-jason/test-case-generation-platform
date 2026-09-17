"""multiuser: users + user_llm_configs，knowledge_bases 加归属/可见性，
test_cases / llm_usage 加 owner_id，llm_usage 加 credential_source。

历史数据归属（单机单工作区 → 多用户的一次性迁移）：
- 已存在的知识库全部视为团队库（visibility='team'）、owner 为首个管理员——
  现状就是全员共享，归团队后每个人仍可见；归个人会让其他人的引用瞬间消失。
- 历史用例/批次/流水归首个管理员：批次要求私有，归管理员是「不丢数据 + 不外泄」的
  唯一选择；旧流水全部记为 credential_source='system'（升级前本来只走全局 key）。

首个管理员由 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD 创建（必填，缺失则启动失败）。
"""
import uuid as _uuid

import sqlalchemy as sa
from alembic import op

from app.config import settings
from app.database import now_local
from app.services.auth_service import hash_password

revision = "0003_multiuser"
down_revision = "0002_legacy_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    now = now_local()

    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ── user_llm_configs（1:1）──
    op.create_table(
        "user_llm_configs",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_key_masked", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    admin_id = str(_uuid.uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO users (id, username, password_hash, display_name, is_admin, "
            "is_active, created_at, updated_at) VALUES (:id, :username, :hash, "
            "'管理员', 1, 1, :now, :now)"
        ),
        {
            "id": admin_id,
            "username": settings.ADMIN_USERNAME,
            "hash": hash_password(settings.ADMIN_PASSWORD),
            "now": now,
        },
    )

    # ── knowledge_bases：先加可空两列，回填后再收紧 NOT NULL ──
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("visibility", sa.String(10), nullable=True))
    bind.execute(
        sa.text("UPDATE knowledge_bases SET owner_id = :id, visibility = 'team'"),
        {"id": admin_id},
    )
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.alter_column("owner_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("visibility", existing_type=sa.String(10), nullable=False)
    # 全局唯一换成按可见性区分的两个 partial unique index（batch 重建会保留旧索引，
    # 故在重建完成后显式删旧建新）。
    op.drop_index("ix_knowledge_bases_name", table_name="knowledge_bases")
    op.create_index("ix_knowledge_bases_owner_id", "knowledge_bases", ["owner_id"])
    op.create_index(
        "uq_kb_team_name", "knowledge_bases", ["name"], unique=True,
        sqlite_where=sa.text("visibility = 'team'"),
    )
    op.create_index(
        "uq_kb_personal_owner_name", "knowledge_bases", ["owner_id", "name"], unique=True,
        sqlite_where=sa.text("visibility = 'personal'"),
    )

    # ── test_cases：历史用例归管理员 ──
    with op.batch_alter_table("test_cases") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(36), nullable=True))
        batch.create_index("ix_test_cases_owner_id", ["owner_id"])
    bind.execute(sa.text("UPDATE test_cases SET owner_id = :id"), {"id": admin_id})

    # ── llm_usage：归属 + 额度来源（旧流水全走系统兜底）──
    with op.batch_alter_table("llm_usage") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("credential_source", sa.String(10), nullable=True))
        batch.create_index("ix_llm_usage_owner_id", ["owner_id"])
    bind.execute(
        sa.text("UPDATE llm_usage SET owner_id = :id, credential_source = 'system'"),
        {"id": admin_id},
    )


def downgrade() -> None:
    # 与 0002 一致：SQLite 补列/重建不做不可移植的回滚。
    pass
