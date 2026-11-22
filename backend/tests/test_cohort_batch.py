"""成员样本批量重算场景测试。

验收路径：多选三个分群一起提交 -> 中间一项算到一半中断 ->
单群数据与双组对比分别确认可用范围 -> 补跑 -> 按名单复核人数差。
"""
from __future__ import annotations

from app.services.user_cohort import UserCohortService
from app.services.segment_compare import SegmentCompareService
from app.store import store

OBS_DATE = "2026-11-22"


def _make_cohort(svc: UserCohortService, name: str, condition: str, size: str) -> int:
    entry, missing = svc.create_entry({
        "分群名称": name,
        "分群条件": condition,
        "群组大小": size,
        "更新频率": "每日",
        "最近更新时间": "",
    })
    assert not missing
    return int(entry["id"])


def _make_compare(svc: SegmentCompareService, name: str, a: str, b: str) -> int:
    entry, missing = svc.create_entry({
        "对比名称": name,
        "分群A": a,
        "分群B": b,
        "对比维度": "人数",
        "对比结果摘要": "",
    })
    assert not missing
    return int(entry["id"])


class TestCohortBatchRecompute:
    """批量重算 -> 部分失败 -> 可用性 -> 补跑 -> 复核人数差"""

    def test_full_scenario(self):
        cohort_svc = UserCohortService()
        compare_svc = SegmentCompareService()

        # 准备三个分群：规模 80 / 100 / 60
        id_a = _make_cohort(cohort_svc, "批量场景-高活跃", "近7天登录>=5次", "80")
        id_b = _make_cohort(cohort_svc, "批量场景-中活跃", "近7天登录3-4次", "100")
        id_c = _make_cohort(cohort_svc, "批量场景-低活跃", "近7天登录1-2次", "60")

        # 1) 多选三个分群一起提交，中间一项算到一半中断
        result = cohort_svc.batch_recompute(
            [id_a, id_b, id_c], observation_date=OBS_DATE, interrupt_cohort_id=id_b)
        assert "error" not in result
        batch_id = result["batch_id"]
        assert result["观察日"] == OBS_DATE
        assert result["status"] == "部分完成"

        items = {item["cohort_id"]: item for item in result["items"]}
        assert items[id_a]["status"] == "已确认"
        assert items[id_b]["status"] == "计算失败"
        assert items[id_b]["失败原因"]
        assert items[id_c]["status"] == "已确认"
        # 名单受观察日和当时的分群条件约束
        assert items[id_a]["观察日"] == OBS_DATE
        assert items[id_a]["分群条件"] == "近7天登录>=5次"

        # 运营能看到当前哪些数据能用：A、C 可独立核对，B 要等
        usability = result["usability"]
        assert {u["cohort_id"] for u in usability["usable_cohorts"]} == {id_a, id_c}
        assert [w["cohort_id"] for w in usability["waiting_cohorts"]] == [id_b]
        assert usability["usable_compare_pairs"] == [
            {"分群A": "批量场景-高活跃", "分群B": "批量场景-低活跃"}]

        # 2) 单群数据：已确认的能看名单，中断的提示要补跑
        detail_a = cohort_svc.get_batch_cohort_members(batch_id, id_a)
        assert detail_a["member_count"] == 80
        assert all(m["observation_date"] == OBS_DATE for m in detail_a["members"])
        assert all(m["condition"] == "近7天登录>=5次" for m in detail_a["members"])
        detail_b = cohort_svc.get_batch_cohort_members(batch_id, id_b)
        assert "error" in detail_b
        assert detail_b["status"] == "计算失败"

        # 3) 双组对比：A vs B 要等 B 的名单；A vs C 立即可用
        task_wait = _make_compare(compare_svc, "批量场景-对照AB",
                                  "批量场景-高活跃", "批量场景-中活跃")
        waited = compare_svc.execute_compare_by_batch(task_wait, batch_id)
        assert waited["status"] == "等待名单"
        assert [u["分群名称"] for u in waited["usable_now"]] == ["批量场景-高活跃"]
        assert [w["分群名称"] for w in waited["waiting_for"]] == ["批量场景-中活跃"]
        assert store.find("segment_compare", task_wait)["status"] == "执行中"

        task_ok = _make_compare(compare_svc, "批量场景-对照AC",
                                "批量场景-高活跃", "批量场景-低活跃")
        done = compare_svc.execute_compare_by_batch(task_ok, batch_id)
        assert done["batch_id"] == batch_id
        assert done["观察日"] == OBS_DATE
        # 响应关联所用分群与样本
        assert done["cohort_a"]["cohort_id"] == id_a
        assert done["cohort_a"]["分群条件"] == "近7天登录>=5次"
        assert done["cohort_a"]["member_count"] == 80
        assert done["cohort_a"]["sample_members"]
        assert done["cohort_b"]["member_count"] == 60
        # 按名单复核人数差：|80 - 60| = 20，交集 60
        assert done["headcount_diff"] == 20
        assert done["overlap_count"] == 60
        assert store.find("segment_compare", task_ok)["status"] == "已完成"

        # 4) 中断项的分群条件在补跑前被调整，随后补跑
        cohort_b = store.find("user_cohort", id_b)
        cohort_b["分群条件"] = "近7天登录3-4次（剔除测试账号）"
        rerun = cohort_svc.rerun_batch(batch_id)
        assert "error" not in rerun
        assert rerun["status"] == "全部完成"
        assert rerun["rerun_cohort_ids"] == [id_b]
        assert set(rerun["kept_cohort_ids"]) == {id_a, id_c}

        # 补跑只更正本窗口内未完成项；已确认的沿用既有快照，还原当时条件
        snapshot = cohort_svc.get_batch_cohort_members(batch_id, id_a)
        assert snapshot["分群条件"] == "近7天登录>=5次"
        assert snapshot["观察日"] == OBS_DATE
        rerun_b = cohort_svc.get_batch_cohort_members(batch_id, id_b)
        assert rerun_b["status"] == "已确认"
        assert rerun_b["分群条件"] == "近7天登录3-4次（剔除测试账号）"
        assert rerun_b["观察日"] == OBS_DATE  # 仍是本观察窗
        assert rerun_b["member_count"] == 100

        # 5) 补算以后按名单复核人数差：|80 - 100| = 20，交集 80
        finished = compare_svc.execute_compare_by_batch(task_wait, batch_id)
        assert finished["headcount_diff"] == 20
        assert finished["overlap_count"] == 80
        assert finished["cohort_b"]["分群条件"] == "近7天登录3-4次（剔除测试账号）"
        assert store.find("segment_compare", task_wait)["status"] == "已完成"

    def test_batch_recompute_validates_input(self):
        svc = UserCohortService()
        assert "error" in svc.batch_recompute([])
        assert "error" in svc.batch_recompute([999999])

    def test_rerun_missing_batch(self):
        svc = UserCohortService()
        assert "error" in svc.rerun_batch("B00000000-000")

    def test_list_batches_and_snapshot(self):
        svc = UserCohortService()
        cid = _make_cohort(svc, "批量场景-独立批次", "近30天有下单", "50")
        created = svc.batch_recompute([cid], observation_date=OBS_DATE)
        batch_id = created["batch_id"]

        batches = svc.list_batches()
        assert any(b["batch_id"] == batch_id for b in batches)
        summary = next(b for b in batches if b["batch_id"] == batch_id)
        assert summary["status"] == "全部完成"
        assert summary["confirmed_count"] == 1

        snapshot = svc.get_batch_snapshot(batch_id)
        assert snapshot is not None
        assert snapshot["items"][0]["member_count"] == 50
        assert svc.get_batch_snapshot("B00000000-000") is None

    def test_compare_rejects_cohort_outside_batch(self):
        cohort_svc = UserCohortService()
        compare_svc = SegmentCompareService()
        id_in = _make_cohort(cohort_svc, "批量场景-窗内", "条件窗内", "40")
        id_out = _make_cohort(cohort_svc, "批量场景-窗外", "条件窗外", "40")
        batch_id = cohort_svc.batch_recompute([id_in], observation_date=OBS_DATE)["batch_id"]

        task_id = _make_compare(compare_svc, "批量场景-跨窗对照",
                                "批量场景-窗内", "批量场景-窗外")
        result = compare_svc.execute_compare_by_batch(task_id, batch_id)
        assert "error" in result
        assert "批量场景-窗外" in result["error"]
        assert store.find("user_cohort", id_out) is not None
