"""Phase 7.0 Curling WebSocket Transport Skeleton 测试。

测试只覆盖传输层和 Raw Parser，不连接真实公网，也不映射到 TriggerEvent/Position。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.adapters.stone.auth import CurlingAuthError, CurlingTokenClient
from app.adapters.stone.websocket import CurlingWebSocketConfigError, CurlingWebSocketTransport
from app.models.curling_raw import (
    GenericRawMessage,
    FullDataRawMessage,
    HeartbeatRawMessage,
    MalformedRawMessage,
    MatchStartRawMessage,
    MatchStopRawMessage,
    StoneStateRawMessage,
    TrajectoryRawMessage,
    parse_raw_curling_message,
)
from app.models.event import TriggerEvent


class FakeHttpClient:
    """TokenClient 测试用 HTTP 客户端。"""

    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.requests: list[dict] = []

    def post(self, url: str, json: dict, timeout: float) -> httpx.Response:
        """记录请求并返回预设响应。"""

        self.requests.append({"url": url, "json": json, "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeWebSocket:
    """Transport 测试用 WebSocket。"""

    def __init__(self, messages: list[str | bytes] | None = None, fail_on_recv: bool = False) -> None:
        self.messages = messages or []
        self.fail_on_recv = fail_on_recv
        self.closed = False

    async def recv(self) -> str | bytes:
        """返回一条消息或模拟断线。"""

        if self.fail_on_recv:
            raise RuntimeError("disconnect")
        if not self.messages:
            raise RuntimeError("disconnect")
        return self.messages.pop(0)

    async def close(self) -> None:
        """记录关闭状态。"""

        self.closed = True


class FakeTokenClient:
    """Transport 测试用 token client。"""

    def __init__(self, token: str = "secret-token") -> None:
        self.token = token
        self.calls = 0

    def fetch_token(self) -> str:
        """返回固定 token。"""

        self.calls += 1
        return self.token


def _json_response(data: dict, status_code: int = 200) -> httpx.Response:
    """构造带 request 的 httpx.Response，便于 raise_for_status。"""

    return httpx.Response(status_code, json=data, request=httpx.Request("POST", "http://curling.local/wanghe/sys/mLogin"))


def test_token_success_parses_result_token() -> None:
    """成功登录时应解析 result.token，且登录 JSON 只包含正式文档字段。"""

    client = FakeHttpClient(_json_response({"success": True, "code": 200, "result": {"token": "token-001"}}))
    token = CurlingTokenClient(
        "http://curling.local/wanghe",
        "/sys/mLogin",
        username="user",
        password="password",
        user_id="uid",
        http_client=client,
    ).fetch_token()
    assert token == "token-001"
    assert client.requests[0]["url"] == "http://curling.local/wanghe/sys/mLogin"
    assert client.requests[0]["json"] == {"username": "user", "password": "password"}
    assert "userId" not in client.requests[0]["json"]


def test_token_login_failure_and_missing_token() -> None:
    """登录失败或缺少 token 都应返回可控异常。"""

    failed = CurlingTokenClient("http://curling.local", "/sys/mLogin", http_client=FakeHttpClient(_json_response({"success": False, "code": 500, "result": {}})))
    try:
        failed.fetch_token()
    except CurlingAuthError as exc:
        assert "failed" in str(exc)
    else:
        raise AssertionError("login failure should raise")

    missing = CurlingTokenClient("http://curling.local", "/sys/mLogin", http_client=FakeHttpClient(_json_response({"success": True, "code": 0, "result": {}})))
    try:
        missing.fetch_token()
    except CurlingAuthError as exc:
        assert "token missing" in str(exc)
    else:
        raise AssertionError("missing token should raise")


def test_parse_type_1_type_2_and_type_12() -> None:
    """type=1/2/12 只解析 Raw 消息，不驱动 MatchService。"""

    assert isinstance(parse_raw_curling_message('{"type":1,"laneId":"curlingLane6Data"}'), MatchStartRawMessage)
    assert isinstance(parse_raw_curling_message('{"type":2,"laneId":"curlingLane6Data"}'), MatchStopRawMessage)
    full_data = parse_raw_curling_message('{"type":12,"stone0":[],"message":"connected"}')
    assert isinstance(full_data, FullDataRawMessage)
    assert isinstance(full_data, HeartbeatRawMessage)
    assert full_data.raw["stone0"] == []


def test_parse_type_3_trajectory_keeps_lane_id_raw() -> None:
    """type=3 只解析 trajectoryData，laneId 原样保留，不做 sheet 映射。"""

    message = parse_raw_curling_message(
        '{"type":3,"laneId":"curlingLane6Data","trajectoryData":[{"laneId":"curlingLane6Data","tagId":"tag_001","time":123,"x":1.5,"y":2.5}]}'
    )
    assert isinstance(message, TrajectoryRawMessage)
    assert message.lane_id == "curlingLane6Data"
    assert message.trajectory_data[0].lane_id == "curlingLane6Data"
    assert message.trajectory_data[0].tag_id == "tag_001"
    assert message.trajectory_data[0].x == 1.5


def test_parse_type_4_state_does_not_map_to_trigger_event() -> None:
    """type=4 保留 stoneState/hogline 原始语义，不映射内部 TriggerEvent。"""

    message = parse_raw_curling_message(
        '{"type":4,"laneId":"curlingLane6Data","movingStoneTagId":"tag_002","stoneState":"hogline1","hogLine1Timing":10,"hogLine2Timing":20,"totalTiming":30}'
    )
    assert isinstance(message, StoneStateRawMessage)
    assert not isinstance(message, TriggerEvent)
    assert message.lane_id == "curlingLane6Data"
    assert message.moving_stone_tag_id == "tag_002"
    assert message.stone_state == "hogline1"
    assert not hasattr(message, "event_type")


def test_unknown_type_and_malformed_json_are_controlled() -> None:
    """未知 type 和坏 JSON 不应让传输层失控。"""

    unknown = parse_raw_curling_message('{"type":99,"laneId":"rawLane"}')
    malformed = parse_raw_curling_message('{bad json')
    assert isinstance(unknown, GenericRawMessage)
    assert unknown.type == 99
    assert isinstance(malformed, MalformedRawMessage)
    assert "malformed_json" in malformed.error


def test_websocket_connect_sends_token_as_subprotocol() -> None:
    """Transport 通过 subprotocols 传 token，封装 Sec-WebSocket-Protocol 细节。"""

    calls = []

    async def connector(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return FakeWebSocket(['{"type":12}'])

    transport = CurlingWebSocketTransport(
        "ws://curling.local/ws",
        FakeTokenClient("secret-token"),
        reconnect_seconds=7,
        connect_timeout_seconds=11,
        connector=connector,
    )
    asyncio.run(transport.connect())
    assert calls[0]["args"] == ("ws://curling.local/ws",)
    assert calls[0]["kwargs"]["subprotocols"] == ["secret-token"]
    assert calls[0]["kwargs"]["open_timeout"] == 11
    assert transport.reconnect_seconds == 7


def test_websocket_receive_decodes_json_and_disconnect_is_controlled() -> None:
    """Transport 能解析消息；断线时返回 None 而不是不可控异常。"""

    async def run_case() -> None:
        good = FakeWebSocket(['{"type":3,"laneId":"rawLane","trajectoryData":[]}'])
        transport = CurlingWebSocketTransport("ws://curling.local/ws", FakeTokenClient(), connector=lambda **kwargs: good)
        transport._websocket = good
        message = await transport.receive()
        assert isinstance(message, TrajectoryRawMessage)
        broken = FakeWebSocket(fail_on_recv=True)
        transport._websocket = broken
        assert await transport.receive() is None
        assert not transport.connected

    asyncio.run(run_case())


def test_websocket_reconnect_uses_configured_delay() -> None:
    """receive_with_reconnect 在断线后按配置重连一次。"""

    async def run_case() -> None:
        sleeps = []
        sockets = [FakeWebSocket(fail_on_recv=True), FakeWebSocket(['{"type":12}'])]
        calls = []

        async def connector(*args, **kwargs):
            calls.append(kwargs)
            return sockets.pop(0)

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)

        transport = CurlingWebSocketTransport(
            "ws://curling.local/ws",
            FakeTokenClient(),
            reconnect_seconds=4.5,
            connector=connector,
            sleep=sleep,
        )
        await transport.connect()
        message = await transport.receive_with_reconnect()
        assert isinstance(message, FullDataRawMessage)
        assert sleeps == [4.5]
        assert transport.reconnect_count == 1
        assert len(calls) == 2

    asyncio.run(run_case())


def test_no_secret_values_in_logs(caplog) -> None:
    """日志不得输出 username/password/token。"""

    async def connector(*args, **kwargs):
        return FakeWebSocket(['{"type":12}'])

    with caplog.at_level(logging.INFO):
        transport = CurlingWebSocketTransport("ws://curling.local/ws", FakeTokenClient("token-secret"), connector=connector)
        asyncio.run(transport.connect())
        asyncio.run(transport.close())
    logs = caplog.text
    assert "token-secret" not in logs
    assert "password" not in logs


def test_malformed_json_received_as_model() -> None:
    """WebSocket 收到坏 JSON 时返回 MalformedRawMessage。"""

    async def run_case() -> None:
        websocket = FakeWebSocket(["{bad json"])
        transport = CurlingWebSocketTransport("ws://curling.local/ws", FakeTokenClient())
        transport._websocket = websocket
        message = await transport.receive()
        assert isinstance(message, MalformedRawMessage)

    asyncio.run(run_case())


def test_token_http_error_is_controlled() -> None:
    """HTTP 状态错误应收敛为 CurlingAuthError。"""

    response = _json_response({"success": False}, status_code=500)
    client = CurlingTokenClient("http://curling.local", "/sys/getToken", http_client=FakeHttpClient(response))
    try:
        client.fetch_token()
    except CurlingAuthError as exc:
        assert "http error" in str(exc)
    else:
        raise AssertionError("http error should raise")


def test_non_object_or_missing_type_is_malformed() -> None:
    """非对象 JSON 或缺少 type 时返回 MalformedRawMessage。"""

    assert isinstance(parse_raw_curling_message('[1, 2, 3]'), MalformedRawMessage)
    missing = parse_raw_curling_message('{"laneId":"rawLane"}')
    assert isinstance(missing, MalformedRawMessage)
    assert missing.error == "type_is_required"


def test_websocket_receive_bytes_message() -> None:
    """WebSocket bytes 消息按 UTF-8 解码后进入 Raw Parser。"""

    async def run_case() -> None:
        websocket = FakeWebSocket([b'{"type":12}'])
        transport = CurlingWebSocketTransport("ws://curling.local/ws", FakeTokenClient())
        transport._websocket = websocket
        assert isinstance(await transport.receive(), FullDataRawMessage)

    asyncio.run(run_case())


def test_websocket_url_user_id_placeholder_is_encoded_and_token_stays_subprotocol() -> None:
    """WS URL 支持 {userId} 占位，userId 只用于路径且会做 path segment 编码。"""

    calls = []

    async def connector(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return FakeWebSocket(['{"type":12}'])

    transport = CurlingWebSocketTransport(
        "ws://example:8922/wanghe/curlingWebSocket/{userId}",
        FakeTokenClient("secret-token"),
        user_id="user 001/A",
        connector=connector,
    )
    asyncio.run(transport.connect())
    assert calls[0]["args"] == ("ws://example:8922/wanghe/curlingWebSocket/user%20001%2FA",)
    assert calls[0]["kwargs"]["subprotocols"] == ["secret-token"]


def test_websocket_complete_url_is_not_appended_with_user_id() -> None:
    """完整 WS URL 原样使用，不重复追加 userId。"""

    calls = []

    async def connector(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return FakeWebSocket(['{"type":12}'])

    transport = CurlingWebSocketTransport(
        "ws://example:8922/wanghe/curlingWebSocket/user001",
        FakeTokenClient(),
        user_id="user001",
        connector=connector,
    )
    asyncio.run(transport.connect())
    assert calls[0]["args"] == ("ws://example:8922/wanghe/curlingWebSocket/user001",)


def test_websocket_placeholder_requires_user_id() -> None:
    """WS URL 含 {userId} 但未配置 userId 时应受控失败，且不请求 token。"""

    token_client = FakeTokenClient()
    transport = CurlingWebSocketTransport("ws://example/wanghe/curlingWebSocket/{userId}", token_client)
    try:
        asyncio.run(transport.connect())
    except CurlingWebSocketConfigError as exc:
        assert "CURLING_USER_ID" in str(exc)
    else:
        raise AssertionError("missing userId should raise")
    assert token_client.calls == 0


def test_settings_defaults_follow_websocket_doc() -> None:
    """默认登录 path 不再使用旧 /sys/getToken。"""

    from app.core.config import Settings

    settings = Settings()
    assert settings.login_path == "/sys/mLogin"


def test_settings_read_curling_websocket_env(monkeypatch) -> None:
    """Settings 应读取 CURLING_ 前缀的真实冰壶连接配置。"""

    from app.core.config import Settings

    monkeypatch.setenv("CURLING_WS_ENABLED", "true")
    monkeypatch.setenv("CURLING_API_BASE_URL", "http://curling.local/wanghe")
    monkeypatch.setenv("CURLING_WS_URL", "ws://curling.local/wanghe/curlingWebSocket/{userId}")
    monkeypatch.setenv("CURLING_LOGIN_PATH", "/sys/mLogin")
    monkeypatch.setenv("CURLING_USERNAME", "user")
    monkeypatch.setenv("CURLING_PASSWORD", "secret-password")
    monkeypatch.setenv("CURLING_USER_ID", "user-001")
    monkeypatch.setenv("CURLING_WS_RECONNECT_SECONDS", "8")
    monkeypatch.setenv("CURLING_WS_CONNECT_TIMEOUT_SECONDS", "9")
    settings = Settings()
    assert settings.ws_enabled is True
    assert settings.api_base_url == "http://curling.local/wanghe"
    assert settings.ws_url == "ws://curling.local/wanghe/curlingWebSocket/{userId}"
    assert settings.login_path == "/sys/mLogin"
    assert settings.username == "user"
    assert settings.password == "secret-password"
    assert settings.user_id == "user-001"
    assert settings.ws_reconnect_seconds == 8
    assert settings.ws_connect_timeout_seconds == 9
