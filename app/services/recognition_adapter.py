"""投壶人员识别适配器。

真实模块交付后，只替换本 Adapter 内部调用，不修改主业务流程。
"""

class RecognitionAdapter:
    """人员识别统一调用边界。"""

    def recognize(self, clip_path: str, candidate_player_ids: list[str] | None = None) -> dict:
        """返回与正式 ThrowerRecognizer 协议一致的 Mock 结果。"""

        return {
            "player_id": "player_001",
            "player_snapshot": "mock_player.jpg",
            "confidence": 0.99,
            "status": "recognized",
        }
