"""Phase 7.1 Position Adapter 与 PositionCache 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.stone.position_adapter import TrajectoryPositionAdapter
from app.core.config import ConfigManager, Settings, SiteConfig
from app.models.curling_raw import StoneStateRawMessage, TrajectoryRawMessage, parse_raw_curling_message
from app.models.stone import StonePosition
from app.services.position_cache import PositionCache


def _site_config() -> dict:
    """构造测试用现场配置；fake 坐标只用于测试，不代表真实现场。"""

    return {
        "site_id": "phase7_position_test",
        "sheets": [
            {"sheet_id": "sheet_01", "enabled": True, "position_lane_id": "legacy_position_lane_01"},
            {"sheet_id": "sheet_02", "enabled": True, "position_lane_id": "legacy_position_lane_02"},
        ],
        "lane_mappings": [
            {"lane_id": "fake_lane_01", "sheet_id": "sheet_01"},
            {"lane_id": "fake_lane_02", "sheet_id": "sheet_02"},
        ],
        "cameras": [
            {"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}},
        ],
        "calibration": {
            "position": [
                {
                    "sheet_id": "sheet_01",
                    "enabled": True,
                    "position_lane_id": "fake_lane_01",
                    "lane_bounds": {"x_min": 0.0, "x_max": 4.75, "y_min": 0.0, "y_max": 44.5},
                    "ready_zones": {
                        "A": {"x_min": 0.0, "x_max": 4.75, "y_min": 1.0, "y_max": 5.0},
                        "B": {"x_min": 0.0, "x_max": 4.75, "y_min": 39.0, "y_max": 43.0},
                    },
                    "hoglines": {"A": {"y": 10.0}, "B": {"y": 34.0}},
                }
            ]
        },
    }


def _manager() -> ConfigManager:
    """创建隔离的 ConfigManager，避免依赖真实现场坐标。"""

    return ConfigManager(Settings(site_config=_site_config()))


def _raw_type3(*, lane_id: str = "fake_lane_01", inner_lane_id: str | None = "fake_lane_01", tag_id: str = "stone0", time: int = 1786078169550, x: float = 2.376, y: float = 6.268) -> TrajectoryRawMessage:
    """构造接口格式 type=3 Raw Message，trajectoryData 使用真实示例中的单点对象形态。"""

    payload = {
        "type": 3,
        "laneId": lane_id,
        "trajectoryData": {"laneId": inner_lane_id, "tagId": tag_id, "time": time, "x": x, "y": y},
    }
    message = parse_raw_curling_message(json.dumps(payload))
    assert isinstance(message, TrajectoryRawMessage)
    return message


def test_type3_raw_message_enters_position_adapter() -> None:
    """Raw type=3 可直接经 Adapter 转换为标准 StonePosition。"""

    positions = TrajectoryPositionAdapter(_manager()).convert(_raw_type3())
    assert len(positions) == 1
    position = positions[0]
    assert isinstance(position, StonePosition)
    assert position.sheet_id == "sheet_01"
    assert position.lane_id == "fake_lane_01"
    assert position.tag_id == "stone0"
    assert position.timestamp == 1786078169550
    assert position.x == 2.376
    assert position.y == 6.268


def test_type3_list_payload_is_still_supported() -> None:
    """trajectoryData 批量数组形态继续兼容。"""

    payload = {
        "type": 3,
        "laneId": "fake_lane_01",
        "trajectoryData": [
            {"laneId": "fake_lane_01", "tagId": "stone0", "time": 1, "x": 1.0, "y": 2.0},
            {"laneId": "fake_lane_01", "tagId": "stone1", "time": 2, "x": 3.0, "y": 4.0},
        ],
    }
    message = parse_raw_curling_message(json.dumps(payload))
    assert isinstance(message, TrajectoryRawMessage)
    positions = TrajectoryPositionAdapter(_manager()).convert(message)
    assert [position.tag_id for position in positions] == ["stone0", "stone1"]


def test_position_lane_id_maps_to_sheet_id_from_config() -> None:
    """laneId -> sheet_id 必须通过配置映射，不硬编码真实赛道数量。"""

    manager = _manager()
    assert manager.get_sheet_id_by_position_lane("fake_lane_01") == "sheet_01"
    assert manager.get_sheet_id_by_position_lane("fake_lane_02") == "sheet_02"
    assert manager.get_sheet_id_by_position_lane("legacy_position_lane_01") == "sheet_01"


def test_unknown_lane_is_controlled_and_not_cached(caplog) -> None:
    """未知 lane 不猜 sheet，不写入 cache，且以 warning 可观测。"""

    cache = PositionCache(max_size=5)
    adapter = TrajectoryPositionAdapter(_manager())
    positions = adapter.add_to_cache(_raw_type3(lane_id="unknown_lane", inner_lane_id="unknown_lane"), cache)
    assert positions == []
    assert cache.get_latest("sheet_01", "stone0") is None
    assert "unknown position lane ignored" in caplog.text


def test_outer_inner_lane_match_and_mismatch() -> None:
    """外层 laneId 与内层 laneId 一致时正常，冲突时不写入缓存。"""

    adapter = TrajectoryPositionAdapter(_manager())
    cache = PositionCache(max_size=5)
    ok = adapter.add_to_cache(_raw_type3(lane_id="fake_lane_01", inner_lane_id="fake_lane_01"), cache)
    assert len(ok) == 1
    assert cache.get_latest("sheet_01", "stone0") is not None

    mismatch = adapter.add_to_cache(_raw_type3(lane_id="fake_lane_01", inner_lane_id="fake_lane_02", tag_id="stone_bad"), cache)
    assert mismatch == []
    assert cache.get_latest("sheet_01", "stone_bad") is None
    assert cache.get_latest("sheet_02", "stone_bad") is None


def test_missing_outer_lane_uses_inner_lane() -> None:
    """外层 laneId 缺失时允许使用 trajectoryData 内层 laneId。"""

    message = _raw_type3(lane_id=None, inner_lane_id="fake_lane_02")  # type: ignore[arg-type]
    positions = TrajectoryPositionAdapter(_manager()).convert(message)
    assert positions[0].sheet_id == "sheet_02"
    assert positions[0].lane_id == "fake_lane_02"


def test_position_cache_add_latest_recent_and_size_limit() -> None:
    """同一 tag 多个 position 应有限缓存，并自动淘汰旧点。"""

    cache = PositionCache(max_size=3)
    for index in range(5):
        cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=index, x=float(index), y=float(index)))
    latest = cache.get_latest("sheet_01", "stone0")
    recent = cache.get_recent("sheet_01", "stone0")
    assert latest is not None
    assert latest.position.timestamp == 4
    assert [item.position.timestamp for item in recent] == [2, 3, 4]
    assert [item.position.timestamp for item in cache.get_recent("sheet_01", "stone0", limit=2)] == [3, 4]


def test_position_cache_isolates_tags_and_sheets() -> None:
    """同赛道不同 tag、不同赛道同 tag 均不能互相覆盖。"""

    cache = PositionCache(max_size=5)
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=1, x=1, y=1))
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone1", timestamp=2, x=2, y=2))
    cache.add(StonePosition(sheet_id="sheet_02", lane_id="fake_lane_02", tag_id="stone0", timestamp=3, x=3, y=3))
    assert cache.get_latest("sheet_01", "stone0").position.timestamp == 1  # type: ignore[union-attr]
    assert cache.get_latest("sheet_01", "stone1").position.timestamp == 2  # type: ignore[union-attr]
    assert cache.get_latest("sheet_02", "stone0").position.timestamp == 3  # type: ignore[union-attr]


def test_clear_tag_sheet_and_all() -> None:
    """PositionCache 应支持按 tag、sheet 和全部清理。"""

    cache = PositionCache(max_size=5)
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=1, x=1, y=1))
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone1", timestamp=2, x=2, y=2))
    cache.add(StonePosition(sheet_id="sheet_02", lane_id="fake_lane_02", tag_id="stone0", timestamp=3, x=3, y=3))
    cache.clear_tag("sheet_01", "stone0")
    assert cache.get_latest("sheet_01", "stone0") is None
    assert cache.get_latest("sheet_01", "stone1") is not None
    cache.clear_sheet("sheet_01")
    assert cache.get_latest("sheet_01", "stone1") is None
    assert cache.get_latest("sheet_02", "stone0") is not None
    cache.clear()
    assert cache.get_latest("sheet_02", "stone0") is None


def test_duplicate_position_is_not_added_twice() -> None:
    """连续完全重复的点不会快速挤满 deque。"""

    cache = PositionCache(max_size=5)
    position = StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=1, x=1.0, y=1.0)
    assert cache.add(position, received_at_ms=100)
    assert not cache.add(position, received_at_ms=200)
    assert len(cache.get_recent("sheet_01", "stone0")) == 1
    assert cache.get_latest("sheet_01", "stone0").received_at_ms == 100  # type: ignore[union-attr]


def test_source_time_and_received_at_are_separate() -> None:
    """设备 source_time 原样进入 timestamp，received_at_ms 使用服务端写入时间。"""

    cache = PositionCache(max_size=5)
    source_time = 1786078169550
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=source_time, x=1, y=1), received_at_ms=123)
    latest = cache.get_latest("sheet_01", "stone0")
    assert latest is not None
    assert latest.position.timestamp == source_time
    assert latest.received_at_ms == 123
    assert latest.received_at_ms != latest.position.timestamp


def test_out_of_order_source_time_is_accepted_as_latest_received() -> None:
    """source_time 倒退不崩溃，latest 仍按最新收到定义。"""

    cache = PositionCache(max_size=5)
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=20, x=2, y=2))
    cache.add(StonePosition(sheet_id="sheet_01", lane_id="fake_lane_01", tag_id="stone0", timestamp=10, x=1, y=1))
    latest = cache.get_latest("sheet_01", "stone0")
    assert latest is not None
    assert latest.position.timestamp == 10


def test_calibration_config_loads_fake_ready_zones_and_hoglines() -> None:
    """标定模型能表达 lane_bounds、A/B_READY_ZONE 和 A/B 物理 hogline。"""

    calibration = _manager().get_position_calibration("sheet_01")
    assert calibration.enabled
    assert calibration.position_lane_id == "fake_lane_01"
    assert calibration.lane_bounds is not None
    assert calibration.lane_bounds.x_max == 4.75
    assert calibration.ready_zones["A"] is not None
    assert calibration.ready_zones["B"].y_min == 39.0  # type: ignore[union-attr]
    assert calibration.hoglines["A"].y == 10.0  # type: ignore[union-attr]
    assert calibration.hoglines["B"].y == 34.0  # type: ignore[union-attr]


def test_uncalibrated_config_is_safe() -> None:
    """正式配置未标定时仍能加载，字段保持 null/disabled。"""

    site = SiteConfig.model_validate({
        "site_id": "uncalibrated",
        "sheets": [{"sheet_id": "sheet_01", "position_lane_id": None, "trigger_lane_id": None}],
        "cameras": [{"camera_id": "overview_A", "camera_role": "overview", "source_provider": "local_file", "source_config": {}}],
    })
    assert site.calibration.position == []
    manager = ConfigManager(Settings(site_config=site.model_dump()))
    calibration = manager.get_position_calibration("sheet_01")
    assert not calibration.enabled
    assert calibration.lane_bounds is None
    assert calibration.ready_zones == {"A": None, "B": None}
    assert calibration.hoglines == {"A": None, "B": None}


def test_type4_semantics_are_not_handled_by_position_adapter() -> None:
    """Phase 7.1 不处理 stoneState，也不生成 TriggerEvent。"""

    message = parse_raw_curling_message(json.dumps({"type": 4, "laneId": "fake_lane_01", "stoneState": "start"}))
    assert isinstance(message, StoneStateRawMessage)
    assert TrajectoryPositionAdapter(_manager()).convert(message) == []


def test_phase71_does_not_call_director_or_throw_state_machine() -> None:
    """Position Adapter / Cache 边界不依赖 Director、ThrowStateMachine 或 direction_locked。"""

    adapter_source = Path("app/adapters/stone/position_adapter.py").read_text(encoding="utf-8")
    cache_source = Path("app/services/position_cache.py").read_text(encoding="utf-8")
    combined = adapter_source + cache_source
    assert "DirectorService" not in combined
    assert "DirectorRuleService" not in combined
    assert "ThrowStateMachine" not in combined
    assert "TriggerEvent" not in combined
    assert "direction_locked" not in combined
