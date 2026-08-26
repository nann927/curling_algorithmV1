"""真实冰壶 WebSocket Transport 骨架。

Transport 只负责连接、收包、断线和重连；不把 Raw 消息映射到内部 TriggerEvent/StonePosition。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import quote

import websockets

from app.adapters.stone.auth import CurlingTokenClient
from app.models.curling_raw import RawCurlingMessage, parse_raw_curling_message

logger = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    """Transport 使用的最小 WebSocket 能力，方便测试注入 fake websocket。"""

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


WebSocketConnector = Callable[..., Awaitable[WebSocketLike]]


class CurlingWebSocketConfigError(ValueError):
    """冰壶 WebSocket 连接配置错误。"""


class CurlingWebSocketTransport:
    """冰壶 WebSocket 传输层客户端。"""

    def __init__(
        self,
        ws_url: str,
        token_client: CurlingTokenClient,
        *,
        reconnect_seconds: float = 3.0,
        connect_timeout_seconds: float = 5.0,
        user_id: str | None = None,
        connector: WebSocketConnector | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.user_id = user_id
        self.reconnect_seconds = reconnect_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self._token_client = token_client
        self._connector = connector or websockets.connect
        self._sleep = sleep or asyncio.sleep
        self._websocket: WebSocketLike | None = None
        self._running = False
        self.reconnect_count = 0

    @property
    def connected(self) -> bool:
        """返回当前是否持有 WebSocket 连接对象。"""

        return self._websocket is not None

    async def connect(self) -> None:
        """获取 token 并连接 WebSocket；token 通过 Sec-WebSocket-Protocol 传递。"""

        ws_url = self._resolved_ws_url()
        token = self._token_client.fetch_token()
        self._websocket = await self._connector(
            ws_url,
            subprotocols=[token],
            open_timeout=self.connect_timeout_seconds,
        )
        self._running = True
        logger.info("curling websocket connected url=%s", ws_url)

    async def receive(self) -> RawCurlingMessage | None:
        """接收并解析一条 Raw 消息；断线时返回 None，由上层决定是否重连。"""

        if self._websocket is None:
            return None
        try:
            raw = await self._websocket.recv()
        except Exception as exc:  # noqa: BLE001 - 传输层需把断线收敛为可控状态。
            logger.warning("curling websocket disconnected: %s", exc.__class__.__name__)
            self._websocket = None
            return None
        if isinstance(raw, bytes):
            raw_text = raw.decode("utf-8", errors="replace")
        else:
            raw_text = raw
        return parse_raw_curling_message(raw_text)

    async def close(self) -> None:
        """关闭 WebSocket 连接。"""

        self._running = False
        websocket = self._websocket
        self._websocket = None
        if websocket is not None:
            await websocket.close()
        logger.info("curling websocket closed")

    async def reconnect(self) -> None:
        """按配置延迟后重新连接。"""

        self.reconnect_count += 1
        await self.close()
        await self._sleep(self.reconnect_seconds)
        await self.connect()

    async def receive_with_reconnect(self) -> RawCurlingMessage | None:
        """读取一条消息；如果已断线则按配置执行一次重连。"""

        message = await self.receive()
        if message is not None or not self._running:
            return message
        await self.reconnect()
        return await self.receive()

    def _resolved_ws_url(self) -> str:
        """解析 WebSocket URL；完整 URL 原样使用，{userId} 由配置值替换。"""

        if "{userId}" not in self.ws_url:
            return self.ws_url
        if not self.user_id:
            raise CurlingWebSocketConfigError("CURLING_USER_ID is required when CURLING_WS_URL contains {userId}")
        return self.ws_url.replace("{userId}", quote(self.user_id, safe=""))
