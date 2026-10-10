"""确定性检测：数值前后矛盾、大段重复、超范围残留。"""

from __future__ import annotations

from bidwb.checks import Passage
from bidwb.checks.consistency import check, duplicate_passages, numeric_conflicts
from bidwb.checks.scope import residual_scope


def _p(n: int, text: str) -> Passage:
    return Passage(f"evd_{n}", n, text)


def test_same_quantity_with_different_values_is_reported_once_with_pages() -> None:
    found = numeric_conflicts(
        [_p(3, "沉井最大开挖深度为12m，采用不排水下沉。"), _p(9, "基坑最大开挖深度为 15 m。"), _p(12, "管道DN300长度为200m。")]
    )
    assert len(found) == 1
    assert "最大开挖深度" in found[0].statement and "12m（第 3 页）" in found[0].statement and "15m（第 9 页）" in found[0].statement
    assert (
        found[0].category == "consistency"
        and found[0].nature == "fact_conflict"
        and set(found[0].evidence_ids) == {"evd_1" if False else "evd_3", "evd_9"}
    )


def test_same_value_and_different_models_do_not_conflict() -> None:
    assert (
        numeric_conflicts(
            [_p(1, "DN300管道长度为200m。"), _p(2, "DN500管道长度为350m。"), _p(3, "最大开挖深度为5.0m。"), _p(4, "最大开挖深度为5m。")]
        )
        == []
    )


def test_long_duplicated_passages_are_reported() -> None:
    long = "本工程施工期间必须严格执行文明施工措施，设置围挡并定期洒水降尘，夜间施工须办理审批手续，严禁高噪声设备在居民区附近作业，渣土车辆必须密闭运输并冲洗轮胎后方可上路行驶，施工现场出入口设置洗车槽并安排专人值守，每日清扫路面，保持周边道路整洁，雨天加强巡查排水沟渠通畅情况。"
    found = duplicate_passages([_p(2, long), _p(7, long + "补充。"), _p(8, "工期计划如下。")])
    assert len(found) == 1 and found[0].category == "consistency" and set(found[0].evidence_ids) == {"evd_2", "evd_7"}
    assert check([_p(8, "工期计划如下。")]) == []


def test_scope_residue_lists_objects_missing_from_tender() -> None:
    body = [_p(40, "采用沉井施工，沉井下沉到位后封底。"), _p(41, "沉井位于桩号K1+200。"), _p(5, "道路工程采用水泥稳定碎石基层。")]
    tender = [_p(1, "本项目为道路及排水工程，包含雨水管道与路面。")]
    found = residual_scope(body, tender)
    assert [f.category for f in found] == ["scope"]
    assert "沉井" in found[0].statement and "40、41" in found[0].statement and found[0].nature == "needs_confirmation"
    assert residual_scope(body, [_p(1, "含沉井工程")]) == []
    assert residual_scope(body, []) == []  # 没有招标文本就没有比较基准，不猜
