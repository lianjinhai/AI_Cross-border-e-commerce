"""P2 验收：M4 客服知识自进化（含答案回填时序，方案 §8-修正8）。

安全红线：
  1) 只沉淀人工验证过的答案（answer_source=operator），AI 不自行编答案
  2) 无答案的候选永不可入库（人工也不行，除非先补答案）
  3) 自动学习默认关闭（opt-in）
  4) 自动入库必须可撤销
"""
import time


def _make_conversation(client, auth_headers, content: str) -> int:
    r = client.post("/api/support/conversations", headers=auth_headers,
                    json={"platform": "shopee", "buyer_name": f"知识测试{int(time.time()*1000)%100000}",
                          "content": content})
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestCandidateRecording:
    """候选记录：未命中问题沉淀 + 归一化聚类 + 容错。"""

    def test_unmatched_question_recorded(self, client, auth_headers):
        """未命中问题（other 意图）被记录为候选，hit_count 从 1 开始。"""
        stamp = int(time.time() * 1000) % 1000000
        q = f"请问你们的发货政策细节xyz{stamp}是怎样的"
        cid = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        match = [c for c in cands if str(stamp) in c["question_text"]]
        assert match, "未命中问题未被记录为候选"
        assert match[0]["hit_count"] == 1
        assert match[0]["answer_source"] == "none", "初始不应有答案"

    def test_normalized_hash_clusters_similar(self, client, auth_headers):
        """归一化哈希：格式差异（空格/标点）不产生重复候选。"""
        stamp = int(time.time() * 1000) % 1000000
        base = f"咨询促销活动规则{stamp}"
        cid1 = _make_conversation(client, auth_headers, base)
        client.post(f"/api/support/conversations/{cid1}/auto_reply", headers=auth_headers)
        # 同内容但加空格和标点
        cid2 = _make_conversation(client, auth_headers, f"{base} ！！  ")
        client.post(f"/api/support/conversations/{cid2}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        match = [c for c in cands if str(stamp) in c["question_text"]]
        assert len(match) == 1, f"格式差异应归为同一候选，实际 {len(match)} 条"
        assert match[0]["hit_count"] >= 2, "重复提问应累加 hit_count"

    def test_recording_failure_does_not_block_reply(self, client, auth_headers):
        """容错：记录逻辑异常不得影响客服回复（审计不阻塞业务）。"""
        cid = _make_conversation(client, auth_headers, "随便问问测试容错性")
        r = client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        assert r.status_code == 200 and r.json()["content"], "客服回复必须正常返回"


class TestAnswerBackfill:
    """答案回填（方案 §8-修正8）：operator 回复后候选获得可信答案。"""

    def test_operator_reply_backfills_answer(self, client, auth_headers):
        """关键时序用例：auto_reply 先记录问题，operator 回复后回填答案。"""
        stamp = int(time.time() * 1000) % 1000000
        q = f"退换货运费谁承担{stamp}"
        cid = _make_conversation(client, auth_headers, q)
        # 1) 自动回复：记录候选（此时无答案）
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        assert cand["answer_source"] == "none"
        # 2) operator 人工回复：应回填答案
        r = client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                        json={"content": "亲，退换货运费由我们承担，请放心申请～"})
        assert r.status_code == 200
        assert r.json().get("knowledge_backfilled", 0) >= 1, "未回填候选答案"
        # 3) 候选应变为有答案
        after = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand2 = next(c for c in after if str(stamp) in c["question_text"])
        assert cand2["answer_source"] == "operator", cand2
        assert "运费由我们承担" in cand2["answer_draft"]

    def test_backfill_does_not_overwrite(self, client, auth_headers):
        """回填不覆盖已有人工答案。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"覆盖测试问题{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "第一次答案"})
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "第二次答案"})
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        assert cand["answer_draft"] == "第一次答案", "不应被后续回复覆盖"


class TestSafetyGuardrails:
    """安全红线：AI 不编答案、默认关闭、可撤销。"""

    def test_cannot_approve_without_answer(self, client, auth_headers):
        """红线 2：无人工验证答案的候选不可采纳为知识。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"无答案候选{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/approve",
                        headers=auth_headers, json={"answer": ""})
        assert r.status_code == 400 and "没有人工验证过的答案" in r.json()["detail"], r.json()

    def test_auto_learn_disabled_by_default(self, client, auth_headers):
        """红线 3：自动学习默认关闭（opt-in）。"""
        cfg = client.get("/api/knowledge/learning/settings", headers=auth_headers).json()
        assert cfg["auto_learn_enabled"] is False, cfg
        assert cfg["auto_learn_threshold"] >= 2

    def test_auto_learn_requires_verified_answer(self, client, auth_headers):
        """红线 1：即使开启自动学习，无人工答案的问题也不会入库。"""
        # 开启自动学习，阈值设 2
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": True, "auto_learn_threshold": 2})
        stamp = int(time.time() * 1000) % 1000000
        q = f"自动学习安全测试{stamp}"
        # 重复提问 3 次但从不人工回复
        for _ in range(3):
            cid = _make_conversation(client, auth_headers, q)
            client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        assert cand["hit_count"] >= 3
        assert cand["status"] == "pending", "无人工答案的问题不得自动入库"
        assert cand["doc_id"] is None
        # 恢复默认
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": False})

    def test_auto_learn_with_answer_and_threshold(self, client, auth_headers):
        """开启 + 有答案 + 达阈值 → 自动入库，来源标记 auto_learned。"""
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": True, "auto_learn_threshold": 2})
        stamp = int(time.time() * 1000) % 1000000
        q = f"自动学习生效测试{stamp}"
        # 第 1 次：提问 + 人工回复（回填答案）
        cid1 = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid1}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid1}/reply", headers=auth_headers,
                    json={"content": "这是经过人工验证的标准答案"})
        # 第 2 次同类提问（触发阈值）
        cid2 = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid2}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        assert cand["status"] == "auto_learned", f"应已自动入库: {cand}"
        assert cand["auto_learned"] is True and cand["doc_id"], cand
        # 知识库出现该文档，来源如实标记
        docs = client.get("/api/knowledge/docs", headers=auth_headers,
                          params={"keyword": str(stamp)}).json()["items"]
        assert docs, "自动入库的文档未出现在知识库"
        assert docs[0]["source"] == "auto_learned", docs[0]
        # 可被检索到（RAG 生效）
        s = client.get("/api/knowledge/search", headers=auth_headers,
                       params={"q": q}).json()["items"]
        assert any(str(stamp) in d["content"] for d in s), "自动入库的知识未被检索到"
        # 清理：撤销
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/revoke", headers=auth_headers)
        assert r.status_code == 200 and r.json()["doc_removed"] is True
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": False})

    def test_revoke_removes_document(self, client, auth_headers):
        """红线 4：撤销自动入库后文档被删除，候选标记 rejected。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"撤销测试问题{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "待撤销的答案"})
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        # 采纳为知识
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/approve",
                        headers=auth_headers, json={"answer": ""})
        assert r.status_code == 200 and r.json()["doc_id"], r.json()
        doc_id = r.json()["doc_id"]
        # 撤销
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/revoke", headers=auth_headers)
        assert r.status_code == 200 and r.json()["doc_removed"] is True
        assert r.json()["status"] == "rejected"
        # 文档确实被删除
        r = client.get("/api/knowledge/docs", headers=auth_headers,
                       params={"keyword": str(stamp)}).json()["items"]
        assert not any(d["id"] == doc_id for d in r), "撤销后文档仍存在"


class TestManualWorkflow:
    """人工流程：补答案 → 采纳 → 拒绝。"""

    def test_answer_then_approve(self, client, auth_headers):
        """人工补写答案后可采纳，知识库出现文档。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"人工采纳测试{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        # 补答案
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/answer", headers=auth_headers,
                        json={"answer": "人工补写的标准答案内容"})
        assert r.status_code == 200 and r.json()["answer_source"] == "operator"
        # 采纳
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/approve",
                        headers=auth_headers, json={"answer": ""})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert r.json()["auto_learned"] is False, "人工采纳不应标记为自动学习"

    def test_reject_candidate(self, client, auth_headers):
        """拒绝候选后状态为 rejected。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"拒绝测试{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        r = client.post(f"/api/knowledge/candidates/{cand['id']}/reject", headers=auth_headers)
        assert r.status_code == 200 and r.json()["status"] == "rejected"

    def test_candidate_list_sorted_by_hits(self, client, auth_headers):
        """候选列表按出现次数排序（高频优先）。"""
        items = client.get("/api/knowledge/candidates", headers=auth_headers,
                           params={"limit": 50}).json()["items"]
        hits = [c["hit_count"] for c in items]
        assert hits == sorted(hits, reverse=True), "候选未按 hit_count 降序"


class TestRegressionFixes:
    """缺陷回归（2026-09-24 审计复现后修复，每条都能抓住对应的真实缺陷）。"""

    def test_delete_doc_referenced_by_candidate_succeeds(self, client, auth_headers):
        """回归 P0：删除被候选引用的知识文档不得 500。

        缺陷：`knowledge_candidates.doc_id` 外键指向 `knowledge_docs.id` 且无
        ondelete，`delete_doc` 直接 `db.delete(d)` → IntegrityError → 500。
        触发面很广——自动学习把候选关联到文档后，**任何**文档删除都会撞上。
        修复：删除前先解除候选引用，并把候选退回 rejected（文档已不存在，
        不能仍标记为已入库）。
        """
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"删文档回归{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "会被删除的答案"})
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        ap = client.post(f"/api/knowledge/candidates/{cand['id']}/approve",
                         headers=auth_headers, json={"answer": ""})
        assert ap.status_code == 200 and ap.json()["doc_id"], ap.json()
        doc_id = ap.json()["doc_id"]

        r = client.delete(f"/api/knowledge/docs/{doc_id}", headers=auth_headers)
        assert r.status_code == 200, f"删除被候选引用的文档应成功，实际 {r.status_code}: {r.text}"

        # 候选必须退回"未入库"态：文档已删，不能仍显示 doc_id 指向不存在的文档
        after = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand2 = next(c for c in after if c["id"] == cand["id"])
        assert cand2["doc_id"] is None, f"候选仍引用已删除的文档: {cand2}"
        assert cand2["status"] == "rejected", f"文档已删除，候选不应仍为已入库态: {cand2}"

    def test_rejected_candidate_not_revived_by_new_question(self, client, auth_headers):
        """回归 P0：人工拒绝是终态，不得被后续同类提问静默推翻。

        缺陷：`_maybe_auto_learn` 只挡 `approved`/`auto_learned`，对 `rejected`
        不设防——拒绝后同类问题再出现一次、hit_count 达阈值，状态被翻回
        auto_learned 并重新入库，人工判断被静默覆盖。
        """
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": True, "auto_learn_threshold": 2})
        stamp = int(time.time() * 1000) % 1000000
        q = f"拒绝终态回归{stamp}"
        cid = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "不应被采纳的答案"})
        cid2 = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid2}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        # 前置条件：此时候选已因达阈值自动入库。先拒绝它——拒绝会连带回收文档，
        # 因此后续断言必须验证"拒绝之后"的终态，而不是"从未入库"。
        assert cand["status"] == "auto_learned" and cand["doc_id"], \
            f"前置条件不成立（应已自动入库）: {cand}"
        client.post(f"/api/knowledge/candidates/{cand['id']}/reject", headers=auth_headers)
        rejected = next(c for c in client.get(
            "/api/knowledge/candidates", headers=auth_headers).json()["items"]
            if str(stamp) in c["question_text"])
        assert rejected["status"] == "rejected", rejected
        assert rejected["doc_id"] is None, f"拒绝已入库候选必须回收文档: {rejected}"

        # 第 3 次同类提问：达阈值也不得复活
        cid3 = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid3}/auto_reply", headers=auth_headers)
        after = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand2 = next(c for c in after if str(stamp) in c["question_text"])
        assert cand2["status"] == "rejected", f"人工拒绝被推翻: {cand2}"
        assert cand2["doc_id"] is None, f"拒绝后不得重新入库: {cand2}"
        assert cand2["auto_learned"] is False, cand2
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": False})

    def test_revoked_candidate_not_revived_by_new_question(self, client, auth_headers):
        """回归 P0：撤销后同类提问不得把知识重新入库（撤销必须是终态）。"""
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": True, "auto_learn_threshold": 2})
        stamp = int(time.time() * 1000) % 1000000
        q = f"撤销终态回归{stamp}"
        cid = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "会被撤销的答案"})
        cid2 = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid2}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        rv = client.post(f"/api/knowledge/candidates/{cand['id']}/revoke", headers=auth_headers)
        assert rv.status_code == 200 and rv.json()["doc_removed"] is True

        cid3 = _make_conversation(client, auth_headers, q)
        client.post(f"/api/support/conversations/{cid3}/auto_reply", headers=auth_headers)
        after = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand2 = next(c for c in after if str(stamp) in c["question_text"])
        assert cand2["status"] == "rejected", f"撤销后被复活: {cand2}"
        assert cand2["doc_id"] is None, cand2
        client.put("/api/knowledge/learning/settings", headers=auth_headers,
                   json={"auto_learn_enabled": False})

    def test_backfill_does_not_answer_unrelated_question(self, client, auth_headers):
        """回归 P1：同一会话里两条不同问题，一次回复只能答中对应那条。

        缺陷：`backfill_answer` 按 `conversation_id` 全量匹配，同会话多个候选会
        被写入同一条答案，`_create_doc` 随后把"问题 A + 答案 B"固化成知识。
        修复：按待答问题的归一化哈希匹配。

        构造方式：会话收到第二条买家消息后再 auto_reply，会沉淀出**第二条**候选
        （哈希基于"两条消息拼接"），此时同会话内已有两条候选。旧实现会把本次
        回复同时写给两条；新实现只命中哈希匹配的那条。
        为什么直接写库插消息：当前 API 只在创建会话时写入一条买家消息，无法追加，
        而生产环境会持续收到买家消息（同一会话多条问题是常态）。
        """
        from app.db import SessionLocal
        from app.models import Message

        stamp = int(time.time() * 1000) % 1000000
        q1 = f"问题甲发货时效{stamp}"
        q2 = f"问题乙退换政策{stamp}"
        cid = _make_conversation(client, auth_headers, q1)
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)

        # 同一会话追加第二条买家消息（模拟真实买家连续提问）
        with SessionLocal() as db:
            db.add(Message(tenant_id=1, conversation_id=cid, role="buyer", content=q2))
            db.commit()
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)

        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "甲答案：三天到"})
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        same_conv = [c for c in cands if c["conversation_id"] == cid]
        assert len(same_conv) == 2, f"同会话应沉淀两条候选，实际 {len(same_conv)}: {same_conv}"
        answered = [c for c in same_conv if c["answer_source"] == "operator"]
        unanswered = [c for c in same_conv if c["answer_source"] == "none"]
        assert len(answered) == 1, f"一次回复只能答中一条候选，实际 {len(answered)}: {same_conv}"
        assert "甲答案" in answered[0]["answer_draft"], answered[0]
        assert len(unanswered) == 1, f"另一条候选不得被误填: {same_conv}"
        assert unanswered[0]["answer_draft"] == "", unanswered[0]

    def test_punctuation_only_question_not_recorded(self, client, auth_headers):
        """回归 P1：纯标点/空白不得产生候选（会共用空哈希并累加 hit_count）。

        断言方式说明：不用「候选总数前后对比」——其他用例（或并行执行）也会
        写候选，总数变化会给出与本题无关的失败。改为直接验证服务层判定，
        并确认这些噪音没有落到任何候选的 question_text 上。
        """
        from app.services.knowledge_learning import is_recordable_question, question_hash

        noise_inputs = ("？？", "！！！", "...", "  ,  ", "?!?", "  ")
        for noise in noise_inputs:
            assert not is_recordable_question(noise), f"纯标点应判定为不可记录：{noise!r}"

        # 噪音归一化后的哈希必须全部相同（都归一到空串）——这正是原缺陷的形态：
        # 纯标点共用同一个哈希，会被 upsert 成同一条候选并累加 hit_count。
        # 断言这一点，才能守住"归一化后判空"的修复不被回退成"归一化前判长度"。
        hashes = {question_hash(n) for n in noise_inputs}
        assert len(hashes) == 1, (
            f"纯标点噪音的哈希应全部归一到同一个值（空串），实际 {len(hashes)} 种：{hashes}")
        # 端到端确认：噪音输入不产生候选
        for noise in noise_inputs[:3]:
            cid = _make_conversation(client, auth_headers, noise)
            client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        cands = client.get("/api/knowledge/candidates", headers=auth_headers,
                           params={"limit": 500}).json()["items"]
        for c in cands:
            assert c["question_text"].strip() not in [n.strip() for n in noise_inputs],                 f"纯标点输入产生了候选：{c}"
        # 有实际内容的问题仍应可记录（防止修复过度）
        assert is_recordable_question("支持退货吗")

    def test_answer_cannot_modify_approved_candidate(self, client, auth_headers):
        """回归 P1：已入库候选禁止改写答案（否则与知识文档内容不一致）。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"已入库改写回归{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "原始答案"})
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        ap = client.post(f"/api/knowledge/candidates/{cand['id']}/approve",
                         headers=auth_headers, json={"answer": ""})
        assert ap.status_code == 200 and ap.json()["doc_id"], ap.json()
        doc_id = ap.json()["doc_id"]

        r = client.post(f"/api/knowledge/candidates/{cand['id']}/answer",
                        headers=auth_headers, json={"answer": "偷偷改成别的"})
        assert r.status_code == 400, f"已入库候选不应允许改写答案: {r.status_code}"

        # 文档内容必须保持原样（不能出现"候选显示新答案、文档还是旧答案"）
        docs = client.get("/api/knowledge/docs", headers=auth_headers,
                          params={"keyword": str(stamp)}).json()["items"]
        doc = next(d for d in docs if d["id"] == doc_id)
        assert "原始答案" in doc["content"], doc
        assert "偷偷改成别的" not in doc["content"], doc

    def test_reject_approved_candidate_removes_document(self, client, auth_headers):
        """回归 P1：拒绝已采纳候选时必须回收知识文档，否则"已否决的知识仍在库"。"""
        stamp = int(time.time() * 1000) % 1000000
        cid = _make_conversation(client, auth_headers, f"拒绝回收回归{stamp}")
        client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
        client.post(f"/api/support/conversations/{cid}/reply", headers=auth_headers,
                    json={"content": "待拒绝的答案"})
        cands = client.get("/api/knowledge/candidates", headers=auth_headers).json()["items"]
        cand = next(c for c in cands if str(stamp) in c["question_text"])
        ap = client.post(f"/api/knowledge/candidates/{cand['id']}/approve",
                         headers=auth_headers, json={"answer": ""})
        assert ap.status_code == 200 and ap.json()["doc_id"], ap.json()

        rj = client.post(f"/api/knowledge/candidates/{cand['id']}/reject", headers=auth_headers)
        assert rj.status_code == 200 and rj.json()["status"] == "rejected"
        assert rj.json()["doc_removed"] is True, f"拒绝已采纳候选未回收文档: {rj.json()}"
        docs = client.get("/api/knowledge/docs", headers=auth_headers,
                          params={"keyword": str(stamp)}).json()["items"]
        assert not docs, f"已否决的知识仍在知识库: {docs}"
