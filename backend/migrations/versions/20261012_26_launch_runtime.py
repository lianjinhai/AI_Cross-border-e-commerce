"""D61 Expand 2c：实例/步骤关系、店铺派生稿与事务事件；保留旧业务事实。"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_26"
down_revision = "20261012_25"
branch_labels = None
depends_on = None

REFS = {
    "listings": {"shop_id": "shops", "parent_listing_id": "listings"},
    "workflow_runs": {"product_id": "products", "shop_id": "shops", "listing_id": "listings",
                      "definition_id": "workflow_templates", "previous_run_id": "workflow_runs", "created_by": "users"},
    "workflow_steps": {"assigned_user_id": "users", "assigned_supplier_id": "suppliers"},
}
TEXT = {
    "workflow_runs": {"definition_hash": (64, ""), "environment": (16, "CONTRACT_TEST"),
                      "platform": (32, ""), "market": (8, ""), "fulfillment_mode": (32, ""),
                      "execution_status": (24, "NOT_STARTED"), "platform_status": (24, "UNKNOWN"),
                      "verification_status": (24, "UNKNOWN"), "current_step": (64, "")},
    "workflow_steps": {"business_type": (32, ""), "execution_mode": (24, ""), "actor": (16, ""),
                       "step_status": (24, "PENDING"), "external_status": (128, ""),
                       "external_reference": (128, ""), "external_type": (32, "UNKNOWN")},
}
JSON_FIELDS = {"workflow_runs": {"definition_snapshot": {}, "blocked_reason": {}, "next_action": {}},
               "workflow_steps": {"blocking_reason": {}, "data_snapshot": {}, "result": {}, "evidence_refs": []}}
DATES = {"workflow_runs": ("started_at", "completed_at", "ended_at", "last_synced_at"),
         "workflow_steps": ("deadline_at",)}
INDEXES = {
    "listings": {"ix_listings_shop_id": (["shop_id"], False)},
    "workflow_runs": {"uq_launch_active_slot": (["tenant_id", "product_id", "shop_id", "active_slot"], True),
                      "uq_launch_request_key": (["tenant_id", "idempotency_key"], True),
                      "ix_launch_workspace_shop": (["tenant_id", "workspace_id", "shop_id"], False)},
    "workflow_steps": {"uq_launch_step_code": (["run_id", "step_code"], True)},
}


def _columns(table):
    columns = [sa.Column(name, sa.Integer(), sa.ForeignKey(target + ".id", name=f"fk_{table}_{name}_{target}"), nullable=True)
               for name, target in REFS[table].items()]
    columns += [sa.Column(name, sa.String(size), nullable=False, server_default=default)
                for name, (size, default) in TEXT.get(table, {}).items()]
    columns += [sa.Column(name, sa.JSON(), nullable=False, server_default="[]" if isinstance(default, list) else "{}")
                for name, default in JSON_FIELDS.get(table, {}).items()]
    columns += [sa.Column(name, sa.DateTime(), nullable=True) for name in DATES.get(table, ())]
    if table == "workflow_runs":
        columns += [sa.Column(name, sa.Integer(), nullable=True) for name in ("workspace_id", "workflow_version", "active_slot")]
        columns += [sa.Column("idempotency_key", sa.String(128), nullable=True),
                    sa.Column("revision", sa.Integer(), nullable=False, server_default="0")]
    if table == "workflow_steps":
        columns += [sa.Column("step_code", sa.String(64), nullable=True),
                    sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.Column("input_revision", sa.Integer(), nullable=False, server_default="0")]
    return columns


def _snapshot():
    inspector = sa.inspect(op.get_bind())
    result = {}
    for table in REFS:
        added = {c.name for c in _columns(table)}
        columns = [(c["name"], str(c["type"]), c["nullable"])
                   for c in inspector.get_columns(table) if c["name"] not in added]
        indexes = sorted((i for i in inspector.get_indexes(table) if i["name"] not in INDEXES[table]), key=lambda i: i["name"])
        keys = sorted((k for k in inspector.get_foreign_keys(table) if not set(k["constrained_columns"]) & added),
                      key=lambda k: k["constrained_columns"])
        count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        result[table] = columns, indexes, keys, inspector.get_pk_constraint(table), count
    return result


def upgrade():
    before = _snapshot()
    for table in REFS:
        inspector = sa.inspect(op.get_bind())
        present = {c["name"] for c in inspector.get_columns(table)}
        checks = {c["name"] for c in inspector.get_check_constraints(table)}
        with op.batch_alter_table(table) as batch:
            for column in _columns(table):
                if column.name not in present:
                    batch.add_column(column)
            if table == "workflow_runs" and "ck_workflow_runs_active_slot" not in checks:
                batch.create_check_constraint("ck_workflow_runs_active_slot", "active_slot IS NULL OR active_slot = 1")
        indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
        for name, (columns, unique) in INDEXES[table].items():
            if name not in indexes:
                op.create_index(name, table, columns, unique=unique)
    if "workflow_events" not in sa.inspect(op.get_bind()).get_table_names():
        _create_events()
    assert _snapshot() == before, "Launch 扩展改变旧结构或行数"


def _create_events():
    columns = [sa.Column("id", sa.Integer(), primary_key=True),
               sa.Column("workspace_id", sa.Integer(), nullable=False)]
    for name, target, nullable in (("tenant_id", "tenants", False), ("run_id", "workflow_runs", False),
                                   ("step_id", "workflow_steps", True), ("actor_id", "users", True)):
        columns.append(sa.Column(name, sa.Integer(), sa.ForeignKey(target + ".id", name=f"fk_workflow_events_{name}_{target}"),
                                 nullable=nullable))
    columns += [sa.Column(name, sa.Integer(), nullable=False) for name in ("sequence", "profile_version", "attempts")]
    columns += [sa.Column(name, sa.String(size), nullable=False) for name, size in
                (("event_type", 64), ("idempotency_key", 128), ("source", 32), ("mapping_version", 64),
                 ("delivery_status", 24), ("lease_owner", 64))]
    columns += [sa.Column(name, sa.DateTime(), nullable=False) for name in ("occurred_at", "received_at", "created_at")]
    columns += [sa.Column(name, sa.DateTime(), nullable=True) for name in ("next_attempt_at", "lease_until")]
    columns += [sa.Column(name, sa.JSON(), nullable=False) for name in ("before", "after", "payload", "consumer_receipts")]
    op.create_table("workflow_events", *columns)
    for name, fields, unique in (("ix_workflow_events_tenant_id", ["tenant_id"], False),
                                 ("uq_workflow_event_sequence", ["run_id", "sequence"], True),
                                 ("uq_workflow_event_key", ["tenant_id", "idempotency_key"], True),
                                 ("ix_workflow_event_delivery", ["delivery_status", "next_attempt_at"], False)):
        op.create_index(name, "workflow_events", fields, unique=unique)


def _has_new_facts(table_name):
    table = sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind())
    nullable = {c.name for c in _columns(table_name) if c.nullable}
    for row in op.get_bind().execute(sa.select(table)).mappings():
        if any(row[name] is not None for name in nullable):
            return True
        if any(row[name] != default for name, (_, default) in TEXT.get(table_name, {}).items()):
            return True
        if any(row[name] != default for name, default in JSON_FIELDS.get(table_name, {}).items()):
            return True
        if table_name == "workflow_runs" and (row["revision"] != 0 or row["flow_kind"] != "LEGACY_AUTOMATION"):
            return True
        if table_name == "workflow_steps" and (row["input_revision"] != 0 or not row["required"]):
            return True
    return False


def downgrade():
    before = _snapshot()
    if op.get_bind().execute(sa.text("SELECT count(*) FROM workflow_events")).scalar_one() or any(
            _has_new_facts(table) for table in REFS):
        raise RuntimeError("已有 Launch、店铺草稿或事件，拒绝有损降级；请备份并 forward-fix")
    op.drop_table("workflow_events")
    for table in reversed(REFS):
        with op.batch_alter_table(table) as batch:
            for name in INDEXES[table]:
                batch.drop_index(name)
            if table == "workflow_runs":
                batch.drop_constraint("ck_workflow_runs_active_slot", type_="check")
            for name, target in REFS[table].items():
                batch.drop_constraint(f"fk_{table}_{name}_{target}", type_="foreignkey")
            for column in reversed(_columns(table)):
                batch.drop_column(column.name)
    assert _snapshot() == before, "Launch 降级改变历史结构或行数"
