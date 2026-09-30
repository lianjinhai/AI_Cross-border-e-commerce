"""测试专用：明确模拟人工批准与独立执行，不能把提案成功当发布成功。"""


def approve_and_execute(client, headers, pending):
    assert pending["status"] == "PENDING_APPROVAL" and pending["approval_required"], pending
    action_id = pending["action_id"]
    blocked = client.post(f"/api/actions/{action_id}/execute", headers=headers)
    assert blocked.status_code == 409, blocked.text
    approved = client.post(f"/api/actions/{action_id}/approve", headers=headers,
                           json={"note": "测试人工确认发布内容与目标店铺"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED", approved.text
    executed = client.post(f"/api/actions/{action_id}/execute", headers=headers)
    assert executed.status_code == 200 and executed.json()["status"] == "SUCCESS", executed.text
    return executed.json()["outcome"]["result"]
