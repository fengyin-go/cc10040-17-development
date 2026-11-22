"""分群对比分析领域服务：对比两个分群在不同维度上的差异。

跨模块数据流: user_cohort -> experiment_group -> segment_compare -> anomaly_detector
"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.services.base import BaseModuleService
from app.services.user_cohort import UserCohortService


class SegmentCompareService(BaseModuleService):
    MODULE = "segment_compare"
    ENTITY = "对比任务"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["对比名称", "分群A", "分群B", "对比维度", "对比结果摘要"]
    REQUIRED_FIELDS = ["对比名称", "分群A", "分群B"]
    STATUS_ORDER = ["待执行", "执行中", "已完成", "执行失败"]
    ACTION_RULES = {"执行对比": "执行中", "取消对比": "执行失败"}
    NEGATIVE_ACTIONS = []

    def execute_compare(self, entry_id: int) -> dict[str, Any] | None:
        """执行分群对比分析。

        跨模块数据流: segment_compare -> user_cohort（获取分群数据）
                     segment_compare -> anomaly_detector（异常发现时触发检测）
        """
        task = store.find(self.MODULE, entry_id)
        if task is None:
            return {"error": f"对比任务 {entry_id} 不存在"}

        cohort_a_name = task.get("分群A", "")
        cohort_b_name = task.get("分群B", "")
        compare_dimension = task.get("对比维度", "通用维度")

        # 查找关联的分群数据
        cohort_a = store.find_by_field("user_cohort", "分群名称", cohort_a_name)
        cohort_b = store.find_by_field("user_cohort", "分群名称", cohort_b_name)

        a_size = int(cohort_a[0].get("群组大小", 0)) if cohort_a else 0
        b_size = int(cohort_b[0].get("群组大小", 0)) if cohort_b else 0

        # 模拟对比计算
        diff_percentage = round(abs(a_size - b_size) / max(1, a_size + b_size) * 100, 2)

        has_anomaly = diff_percentage > 30

        if has_anomaly and cohort_a:
            cohort_a_id = int(cohort_a[0].get("id", 0))
            store.record_anomaly(
                metric_id=cohort_a_id,
                severity="warning" if diff_percentage < 50 else "critical",
                description=f"分群 {cohort_a_name} 与 {cohort_b_name} 差值 {diff_percentage}%",
                value=diff_percentage,
                threshold=30.0,
            )

        result = {
            "task_name": task.get("对比名称"),
            "cohort_a": {"name": cohort_a_name, "size": a_size},
            "cohort_b": {"name": cohort_b_name, "size": b_size},
            "dimension": compare_dimension,
            "diff_percentage": diff_percentage,
            "anomaly_detected": has_anomaly,
            "anomaly_severity": "warning" if diff_percentage < 50 else "critical" if has_anomaly else None,
        }

        task["对比结果摘要"] = f"差值 {diff_percentage}%"
        task["status"] = "已完成"
        task["pending"] = False

        return result

    def execute_compare_by_batch(self, entry_id: int, batch_id: str) -> dict[str, Any] | None:
        """按分群批次快照执行对比：查找同一观察窗内已确认的名单。

        响应关联所用的分群与样本（当时条件、观察日、批次号）。任一方名单
        未确认时不出结果：返回当前可用性（哪份名单可独立核对、对照在等谁），
        任务保持执行中，等补跑后再来。
        """
        task = store.find(self.MODULE, entry_id)
        if task is None:
            return {"error": f"对比任务 {entry_id} 不存在"}
        batch = store.get_cohort_batch(batch_id)
        if batch is None:
            return {"error": f"分群批次快照 {batch_id} 不存在"}

        cohort_a_name = task.get("分群A", "")
        cohort_b_name = task.get("分群B", "")
        items = batch.get("items", [])
        item_a = next((i for i in items if i.get("分群名称") == cohort_a_name), None)
        item_b = next((i for i in items if i.get("分群名称") == cohort_b_name), None)

        missing = [name for name, item in ((cohort_a_name, item_a), (cohort_b_name, item_b))
                   if item is None]
        if missing:
            return {"error": f"批次 {batch_id}（观察日 {batch.get('观察日')}）内没有分群："
                             f"{'、'.join(missing)}"}

        confirmed = UserCohortService.ITEM_CONFIRMED
        not_ready = [item for item in (item_a, item_b) if item.get("status") != confirmed]
        if not_ready:
            ready = [item for item in (item_a, item_b) if item.get("status") == confirmed]
            task["status"] = "执行中"
            task["pending"] = True
            task["对比结果摘要"] = (
                f"等待名单：{'、'.join(str(i.get('分群名称')) for i in not_ready)}")
            return {
                "task_name": task.get("对比名称"),
                "batch_id": batch_id,
                "观察日": batch.get("观察日"),
                "status": "等待名单",
                "usable_now": [
                    {"cohort_id": i.get("cohort_id"), "分群名称": i.get("分群名称"),
                     "member_count": i.get("member_count", 0),
                     "提示": "名单已确认，可独立核对"}
                    for i in ready
                ],
                "waiting_for": [
                    {"cohort_id": i.get("cohort_id"), "分群名称": i.get("分群名称"),
                     "status": i.get("status"), "失败原因": i.get("失败原因"),
                     "提示": "补跑批次后再执行对比"}
                    for i in not_ready
                ],
                "message": "同一观察窗内仍有名单未确认，双组对照暂不可用",
            }

        members_a = item_a.get("members", [])
        members_b = item_b.get("members", [])
        ids_a = {m.get("user_id") for m in members_a}
        ids_b = {m.get("user_id") for m in members_b}
        size_a, size_b = len(ids_a), len(ids_b)
        overlap = len(ids_a & ids_b)
        headcount_diff = abs(size_a - size_b)
        diff_percentage = round(headcount_diff / max(1, size_a + size_b) * 100, 2)

        has_anomaly = diff_percentage > 30
        if has_anomaly:
            store.record_anomaly(
                metric_id=int(item_a.get("cohort_id", 0)),
                severity="warning" if diff_percentage < 50 else "critical",
                description=f"分群 {cohort_a_name} 与 {cohort_b_name} 差值 {diff_percentage}%",
                value=diff_percentage,
                threshold=30.0,
            )

        task["对比结果摘要"] = f"人数差 {headcount_diff}（差值 {diff_percentage}%）"
        task["status"] = "已完成"
        task["pending"] = False

        return {
            "task_name": task.get("对比名称"),
            "batch_id": batch_id,
            "观察日": batch.get("观察日"),
            "dimension": task.get("对比维度", "通用维度"),
            "cohort_a": {
                "cohort_id": item_a.get("cohort_id"),
                "分群名称": cohort_a_name,
                "分群条件": item_a.get("分群条件"),
                "member_count": size_a,
                "sample_members": members_a[:5],
            },
            "cohort_b": {
                "cohort_id": item_b.get("cohort_id"),
                "分群名称": cohort_b_name,
                "分群条件": item_b.get("分群条件"),
                "member_count": size_b,
                "sample_members": members_b[:5],
            },
            "headcount_diff": headcount_diff,
            "overlap_count": overlap,
            "diff_percentage": diff_percentage,
            "anomaly_detected": has_anomaly,
            "anomaly_severity": ("warning" if diff_percentage < 50 else "critical")
                                if has_anomaly else None,
        }

    def get_cross_segment_insights(self, entry_id: int) -> dict[str, Any] | None:
        """获取跨分群洞察，关联异常检测结果。

        跨模块数据流: segment_compare -> anomaly_detector
        """
        task = store.find(self.MODULE, entry_id)
        if task is None:
            return None

        # 查找关联的异常记录
        anomalies = [a for a in store.anomaly_records()
                     if task.get("分群A") in str(a.get("描述", ""))
                     or task.get("分群B") in str(a.get("描述", ""))]

        return {
            "task_name": task.get("对比名称"),
            "result_summary": task.get("对比结果摘要"),
            "related_anomalies": len(anomalies),
            "anomaly_details": [
                {"severity": a.get("严重程度"), "desc": a.get("描述"),
                 "time": a.get("时间")}
                for a in anomalies
            ],
        }