"""M4 客服知识自进化：knowledge_candidates 表

未命中问题沉淀为候选；仅「人工验证过的答案」可固化为知识（红线：AI 不编答案）。
答案回填时序见 docs/M4客服知识自进化方案与论证.md §8-修正8。

幂等：建表前检查表是否已存在；不修改、不删除任何既有数据。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260924_14"
down_revision = "20260924_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "knowledge_candidates" in existing:
        print("[Revision 14] knowledge_candidates 已存在，跳过")
        return
    op.create_table(
        "knowledge_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("question_hash", sa.String(32), nullable=False),
        sa.Column("question_text", sa.String(512), nullable=False),
        sa.Column("intent", sa.String(32), server_default="other"),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("hit_count", sa.Integer(), server_default="1"),
        sa.Column("answer_source", sa.String(16), server_default="none"),
        sa.Column("answer_draft", sa.Text()),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("doc_id", sa.Integer(), sa.ForeignKey("knowledge_docs.id"), nullable=True),
        sa.Column("auto_learned", sa.Boolean(), server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_knowledge_candidates_tenant_id", "knowledge_candidates", ["tenant_id"])
    op.create_index("ix_knowledge_candidates_question_hash", "knowledge_candidates",
                    ["question_hash"])
    op.create_index("uq_knowledge_candidate_hash", "knowledge_candidates",
                    ["tenant_id", "question_hash"], unique=True)
    print("[Revision 14] knowledge_candidates 已创建")


def downgrade() -> None:
    if "knowledge_candidates" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("knowledge_candidates")
        print("[Revision 14] knowledge_candidates 已删除")
