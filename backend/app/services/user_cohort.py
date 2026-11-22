"""用户分群领域服务：管理用户分群定义、计算和分群结果存储。

跨模块数据流: user_cohort -> experiment_group -> segment_compare -> anomaly_detector
分群结果被实验分群、分群对比分析和异常检测器消费。
"""
from __future__ import annotations

import time
from typing import Any

from app.store import store
from app.services.base import BaseModuleService


class UserCohortService(BaseModuleService):
    MODULE = "user_cohort"
    ENTITY = "分群结果"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["分群名称", "分群条件", "群组大小", "更新频率", "最近更新时间"]
    REQUIRED_FIELDS = ["分群名称", "分群条件", "群组大小"]
    STATUS_ORDER = ["待计算", "已生成", "已失效"]
    ACTION_RULES = {"重新计算": "已生成", "标记失效": "已失效"}
    NEGATIVE_ACTIONS = []

    # 批次内名单状态
    ITEM_CONFIRMED = "已确认"
    ITEM_FAILED = "计算失败"
    ITEM_PENDING = "待计算"

    @staticmethod
    def _parse_size(cohort: dict[str, Any]) -> int:
        try:
            return max(1, int(cohort.get("群组大小", "100")))
        except (ValueError, TypeError):
            return 100

    @staticmethod
    def _build_members(cohort: dict[str, Any], observation_date: str) -> list[dict[str, Any]]:
        """按观察日和当时的分群条件生成成员名单（真实项目会查询数据源）。"""
        cohort_name = cohort.get("分群名称", "")
        condition = cohort.get("分群条件", "")
        group_size = UserCohortService._parse_size(cohort)
        return [
            {"user_id": f"U{i+1000}", "name": f"用户{i+1}",
             "cohort": cohort_name, "condition": condition,
             "observation_date": observation_date,
             "join_time": observation_date}
            for i in range(min(group_size, 100))
        ]

    @staticmethod
    def _batch_status(items: list[dict[str, Any]]) -> str:
        confirmed = sum(1 for item in items if item.get("status") == UserCohortService.ITEM_CONFIRMED)
        if confirmed == len(items) and items:
            return "全部完成"
        if confirmed > 0:
            return "部分完成"
        return "未完成"

    @staticmethod
    def _usability(batch: dict[str, Any]) -> dict[str, Any]:
        """汇总批次内当前可用性：哪些名单可独立核对、哪些对照还要等。"""
        items = batch.get("items", [])
        usable = [
            {"cohort_id": item.get("cohort_id"), "分群名称": item.get("分群名称"),
             "member_count": item.get("member_count", 0)}
            for item in items if item.get("status") == UserCohortService.ITEM_CONFIRMED
        ]
        waiting = [
            {"cohort_id": item.get("cohort_id"), "分群名称": item.get("分群名称"),
             "status": item.get("status"), "失败原因": item.get("失败原因")}
            for item in items if item.get("status") != UserCohortService.ITEM_CONFIRMED
        ]
        pairs = [
            {"分群A": a.get("分群名称"), "分群B": b.get("分群名称")}
            for idx, a in enumerate(usable) for b in usable[idx + 1:]
        ]
        return {
            "usable_cohorts": usable,
            "waiting_cohorts": waiting,
            "usable_compare_pairs": pairs,
        }

    def batch_recompute(self, cohort_ids: list[int], observation_date: str | None = None,
                        interrupt_cohort_id: int | None = None) -> dict[str, Any]:
        """成员样本批量重算：一次提交多条分群，按同一观察窗生成分群批次快照。

        名单同时受观察日和当时的分群条件约束：每个批次项都快照提交时刻的
        分群条件，成员记录携带观察日。部分失败不阻塞其余分群，已确认的名单
        可独立核对；interrupt_cohort_id 用于演练某一项算到一半中断的场景。
        """
        if not cohort_ids:
            return {"error": "至少选择一条分群"}
        observation_date = observation_date or time.strftime("%Y-%m-%d")

        items: list[dict[str, Any]] = []
        missing: list[int] = []
        for cohort_id in cohort_ids:
            cohort = store.find(self.MODULE, int(cohort_id))
            if cohort is None:
                missing.append(cohort_id)
                continue
            item: dict[str, Any] = {
                "cohort_id": int(cohort_id),
                "分群名称": cohort.get("分群名称", ""),
                "分群条件": cohort.get("分群条件", ""),  # 当时的分群条件快照
                "观察日": observation_date,
                "status": self.ITEM_PENDING,
                "member_count": 0,
                "members": [],
                "确认时间": None,
                "失败原因": None,
            }
            if interrupt_cohort_id is not None and int(cohort_id) == int(interrupt_cohort_id):
                # 算到一半中断：名单未确认，其余分群继续
                item["status"] = self.ITEM_FAILED
                item["失败原因"] = "成员样本扫描中断：计算任务超时退出"
                cohort["status"] = "待计算"
                cohort["pending"] = True
            else:
                members = self._build_members(cohort, observation_date)
                item["status"] = self.ITEM_CONFIRMED
                item["member_count"] = len(members)
                item["members"] = members
                item["确认时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
                cohort["群组大小"] = str(len(members))
                cohort["最近更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
                cohort["status"] = "已生成"
                cohort["pending"] = False
                store.save_cohort_snapshot(int(cohort_id), members)
            items.append(item)

        if not items:
            return {"error": f"分群 {missing} 不存在，未生成批次"}

        batch = store.create_cohort_batch(observation_date, items)
        batch["status"] = self._batch_status(items)
        store.save_cohort_batch(batch)

        return {
            "batch_id": batch["batch_id"],
            "观察日": observation_date,
            "status": batch["status"],
            "items": [self._item_view(item) for item in items],
            "usability": self._usability(batch),
            "missing_cohort_ids": missing,
            "message": f"批次 {batch['batch_id']} {batch['status']}："
                       f"{len(items)} 条分群内 "
                       f"{sum(1 for i in items if i['status'] == self.ITEM_CONFIRMED)} 条名单已确认",
        }

    def rerun_batch(self, batch_id: str) -> dict[str, Any]:
        """补跑：只更正本观察窗内未完成的项目。

        已确认的名单保持既有快照不动（还原当时的分群条件与观察日），
        仅对计算失败/待计算的项按当前条件重新计算，观察日仍为批次观察日。
        """
        batch = store.get_cohort_batch(batch_id)
        if batch is None:
            return {"error": f"分群批次快照 {batch_id} 不存在"}

        rerun_items: list[dict[str, Any]] = []
        kept_items: list[dict[str, Any]] = []
        for item in batch.get("items", []):
            if item.get("status") == self.ITEM_CONFIRMED:
                kept_items.append(item)  # 采纳既有快照，还原当时条件
                continue
            cohort = store.find(self.MODULE, int(item.get("cohort_id", 0)))
            if cohort is None:
                item["status"] = self.ITEM_FAILED
                item["失败原因"] = "分群结果已删除，无法补跑"
                rerun_items.append(item)
                continue
            members = self._build_members(cohort, batch.get("观察日", ""))
            item["分群条件"] = cohort.get("分群条件", "")  # 补跑时刻的条件快照
            item["status"] = self.ITEM_CONFIRMED
            item["member_count"] = len(members)
            item["members"] = members
            item["确认时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
            item["失败原因"] = None
            cohort["群组大小"] = str(len(members))
            cohort["最近更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
            cohort["status"] = "已生成"
            cohort["pending"] = False
            store.save_cohort_snapshot(int(item["cohort_id"]), members)
            rerun_items.append(item)

        batch["status"] = self._batch_status(batch.get("items", []))
        store.save_cohort_batch(batch)

        return {
            "batch_id": batch["batch_id"],
            "观察日": batch.get("观察日"),
            "status": batch["status"],
            "rerun_cohort_ids": [item.get("cohort_id") for item in rerun_items],
            "kept_cohort_ids": [item.get("cohort_id") for item in kept_items],
            "items": [self._item_view(item) for item in batch.get("items", [])],
            "usability": self._usability(batch),
            "message": f"补跑完成：更正 {len(rerun_items)} 项，沿用既有快照 {len(kept_items)} 项",
        }

    def get_batch_snapshot(self, batch_id: str) -> dict[str, Any] | None:
        """查看分群批次快照：各项状态、名单可用性与当时条件。"""
        batch = store.get_cohort_batch(batch_id)
        if batch is None:
            return None
        items = batch.get("items", [])
        return {
            "batch_id": batch["batch_id"],
            "观察日": batch.get("观察日"),
            "创建时间": batch.get("创建时间"),
            "status": batch.get("status") or self._batch_status(items),
            "items": [self._item_view(item) for item in items],
            "usability": self._usability(batch),
        }

    def list_batches(self) -> list[dict[str, Any]]:
        """列出全部批次快照（摘要不带成员明细）。"""
        result = []
        for batch in store.list_cohort_batches():
            items = batch.get("items", [])
            result.append({
                "batch_id": batch["batch_id"],
                "观察日": batch.get("观察日"),
                "创建时间": batch.get("创建时间"),
                "status": batch.get("status") or self._batch_status(items),
                "item_count": len(items),
                "confirmed_count": sum(
                    1 for item in items if item.get("status") == self.ITEM_CONFIRMED),
            })
        return result

    def get_batch_cohort_members(self, batch_id: str, cohort_id: int) -> dict[str, Any]:
        """单群数据核对：仅已确认的名单可查看，未完成的说明要等补跑。"""
        batch = store.get_cohort_batch(batch_id)
        if batch is None:
            return {"error": f"分群批次快照 {batch_id} 不存在"}
        for item in batch.get("items", []):
            if int(item.get("cohort_id", 0)) == int(cohort_id):
                if item.get("status") != self.ITEM_CONFIRMED:
                    return {
                        "error": f"分群「{item.get('分群名称')}」名单未确认"
                                 f"（{item.get('status')}），需补跑批次 {batch_id} 后再核对",
                        "batch_id": batch_id,
                        "cohort_id": int(cohort_id),
                        "status": item.get("status"),
                        "失败原因": item.get("失败原因"),
                    }
                members = item.get("members", [])
                return {
                    "batch_id": batch_id,
                    "观察日": item.get("观察日"),
                    "cohort_id": int(cohort_id),
                    "分群名称": item.get("分群名称"),
                    "分群条件": item.get("分群条件"),
                    "status": item.get("status"),
                    "member_count": item.get("member_count", 0),
                    "确认时间": item.get("确认时间"),
                    "members": members,
                    "sample_members": members[:5],
                }
        return {"error": f"批次 {batch_id} 内没有分群 {cohort_id}"}

    @staticmethod
    def _item_view(item: dict[str, Any]) -> dict[str, Any]:
        """批次项视图：名单只给样本，明细走单群核对接口。"""
        members = item.get("members", [])
        return {
            "cohort_id": item.get("cohort_id"),
            "分群名称": item.get("分群名称"),
            "分群条件": item.get("分群条件"),
            "观察日": item.get("观察日"),
            "status": item.get("status"),
            "member_count": item.get("member_count", 0),
            "确认时间": item.get("确认时间"),
            "失败原因": item.get("失败原因"),
            "sample_members": members[:5],
        }

    def recompute_cohort(self, entry_id: int) -> dict[str, Any] | None:
        """重新计算分群，生成最新的用户列表快照。

        跨模块数据流: user_cohort -> experiment_group（实验分群引用）
                     user_cohort -> segment_compare（对比分析引用）
        """
        cohort = store.find(self.MODULE, entry_id)
        if cohort is None:
            return {"error": f"分群结果 {entry_id} 不存在"}

        cohort_name = cohort.get("分群名称", "")
        condition = cohort.get("分群条件", "")
        try:
            group_size = int(cohort.get("群组大小", "100"))
        except (ValueError, TypeError):
            group_size = 100

        # 模拟分群计算 - 真实项目会查询数据源
        members = [
            {"user_id": f"U{i+1000}", "name": f"用户{i+1}",
             "cohort": cohort_name, "condition": condition,
             "join_time": time.strftime("%Y-%m-%d")}
            for i in range(min(group_size, 100))
        ]

        # 更新分群基本信息
        cohort["群组大小"] = str(len(members))
        cohort["最近更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cohort["status"] = "已生成"
        cohort["pending"] = False

        # 保存快照
        store.save_cohort_snapshot(entry_id, members)

        # 检查是否有引用的实验分组需要更新
        experiment_refs = store.find_by_field("experiment_group", "筛选条件", cohort_name)
        affected_experiments = [e.get("规则名称") for e in experiment_refs]

        return {
            "cohort_id": entry_id,
            "cohort_name": cohort_name,
            "condition": condition,
            "member_count": len(members),
            "updated_at": cohort.get("最近更新时间"),
            "affected_experiments": affected_experiments,
            "sample_members": members[:5],
        }

    def get_cohort_detail(self, entry_id: int) -> dict[str, Any] | None:
        """获取分群详细信息，包括被哪些实验和对比分析引用。

        跨模块数据流: user_cohort -> experiment_group -> segment_compare
        """
        cohort_data = store.get_cohort_analysis(entry_id)
        if cohort_data is None:
            return None

        cohort = cohort_data["cohort"]
        members = store.get_cohort_snapshot(entry_id)

        return {
            "cohort_id": entry_id,
            "cohort_name": cohort.get("分群名称"),
            "condition": cohort.get("分群条件"),
            "group_size": cohort.get("群组大小"),
            "update_frequency": cohort.get("更新频率"),
            "status": cohort.get("status"),
            "member_count": len(members) if members else 0,
            "referenced_by_experiments": [
                {"name": e.get("规则名称"), "id": e.get("id")}
                for e in cohort_data["experiments"]
            ],
            "referenced_by_comparisons": [
                {"name": c.get("对比名称"), "id": c.get("id")}
                for c in cohort_data["comparisons"]
            ],
            "referenced_by_anomaly_rules": len(cohort_data["anomaly_rules"]),
        }