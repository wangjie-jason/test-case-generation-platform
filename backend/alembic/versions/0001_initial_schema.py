"""initial schema.

显式写出每张表，**不用** Base.metadata.create_all。原因：create_all 会随模型定义漂移，
让「初始迁移」变成活动目标，且它的 checkfirst 语义会把已存在的表整表跳过——
两者叠加出一个静默的 schema 漂移陷阱：给模型加一列后，删库重建的开发机由 0001 自动
带上新列、一切正常，于是没人写新 revision，而线上老库永远拿不到那一列
（旧 init_db 里的 _migrate_* 兜底已随本轮改造移除）。迁移必须描述某个确定时刻的结构，
后续每次模型变更都新增一个 revision。

所有 DATETIME 列存的是 naive 的 Asia/Shanghai 本地时间（由 app.database.now_local() 写入），
与 test_cases.created_at 同口径，便于「今日/本周」直接按日期比较。

revision ID / down_revision 的字符串就是版本链，勿改。
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_name", "knowledge_bases", ["name"], unique=True)

    op.create_table(
        "field_dicts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=False),
        sa.Column("field_name", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("data_source", sa.String(500), nullable=True),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("enum_values", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "business_rules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=False),
        sa.Column("rule_name", sa.String(200), nullable=False),
        sa.Column("rule_type", sa.String(20), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "state_machines",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=False),
        sa.Column("entity", sa.String(200), nullable=False),
        sa.Column("from_state", sa.String(200), nullable=False),
        sa.Column("to_state", sa.String(200), nullable=False),
        sa.Column("condition", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "term_mappings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=False),
        sa.Column("ui_term", sa.String(200), nullable=False),
        sa.Column("tech_field", sa.String(200), nullable=False),
        sa.Column("mapping_desc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "prd_documents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_format", sa.String(20), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_ref", sa.String(100), nullable=True),
        # SQLite 没有原生 JSON 类型，SQLAlchemy 的 JSON 落地为 TEXT，读写自动 json.loads/dumps。
        sa.Column("image_tokens", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prd_documents_source_ref", "prd_documents", ["source_ref"])

    op.create_table(
        "defect_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("root_cause", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_case", sa.String(500), nullable=True),
        sa.Column("occurred_at", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "test_cases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("precondition", sa.Text(), nullable=True),
        sa.Column("steps", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(4), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(20), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("knowledge_refs", sa.Text(), nullable=True),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("req_text", sa.Text(), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("edited_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_cases_batch_id", "test_cases", ["batch_id"])

    op.create_table(
        "review_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reject_reason", sa.String(50), nullable=True),
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_stage", "llm_usage", ["stage"])
    op.create_index("ix_llm_usage_batch_id", "llm_usage", ["batch_id"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])


def downgrade() -> None:
    # 先删引用方，再删被引用方：review_records → test_cases，各知识库子表 → knowledge_bases。
    op.drop_table("llm_usage")
    op.drop_table("review_records")
    op.drop_table("test_cases")
    op.drop_table("defect_records")
    op.drop_table("prd_documents")
    op.drop_table("term_mappings")
    op.drop_table("state_machines")
    op.drop_table("business_rules")
    op.drop_table("field_dicts")
    op.drop_table("knowledge_bases")
