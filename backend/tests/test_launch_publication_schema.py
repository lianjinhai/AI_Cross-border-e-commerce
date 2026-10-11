"""发布状态增量的模型契约；迁移演练另用历史结构，不以 create_all 代替。"""

from app.models import Listing, PlatformPublishAttempt


def test_publication_states_are_separate_persistent_columns():
    for model in (Listing, PlatformPublishAttempt):
        columns = model.__table__.c
        assert {"platform_status", "verification_status", "external_object_type"} <= set(columns.keys())
        assert columns.platform_status.default.arg == "UNKNOWN"
        assert columns.verification_status.default.arg == "UNKNOWN"
    assert {"raw_status", "received_at", "mapping_version"} <= set(PlatformPublishAttempt.__table__.c.keys())
