"""真实冰壶 HTTP Token Client。

Phase 7.0 只负责登录拿 token，不记录账号、密码或 token 内容。
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urljoin

import httpx


class CurlingAuthError(RuntimeError):
    """冰壶登录失败或响应缺失 token。"""


class HttpPostClient(Protocol):
    """TokenClient 需要的最小 HTTP 能力，方便测试注入 fake client。"""

    def post(self, url: str, json: dict[str, Any], timeout: float) -> httpx.Response: ...


class CurlingTokenClient:
    """通过配置化登录接口获取 WebSocket token。"""

    def __init__(
        self,
        api_base_url: str,
        login_path: str,
        *,
        username: str | None = None,
        password: str | None = None,
        user_id: str | None = None,
        timeout_seconds: float = 5.0,
        http_client: HttpPostClient | None = None,
    ) -> None:
        self._api_base_url = api_base_url.rstrip("/") + "/"
        self._login_path = login_path.lstrip("/")
        self._username = username
        self._password = password
        # userId 属于 WebSocket URL 路径参数，不属于 websocket.docx 定义的登录请求体。
        self._user_id = user_id
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or httpx.Client(trust_env=False)

    def fetch_token(self) -> str:
        """执行登录并返回 result.token；所有异常统一收敛为 CurlingAuthError。"""

        url = urljoin(self._api_base_url, self._login_path)
        try:
            response = self._http_client.post(url, json=self._login_payload(), timeout=self._timeout_seconds)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise CurlingAuthError("curling auth http error") from exc
        except ValueError as exc:
            raise CurlingAuthError("curling auth response is not json") from exc
        if not isinstance(data, dict):
            raise CurlingAuthError("curling auth response must be object")
        if data.get("success") is False:
            raise CurlingAuthError("curling auth failed")
        code = data.get("code")
        if code not in (None, 0, "0", 200, "200"):
            raise CurlingAuthError("curling auth failed")
        result = data.get("result")
        token = result.get("token") if isinstance(result, dict) else None
        if not token:
            raise CurlingAuthError("curling auth token missing")
        return str(token)

    def _login_payload(self) -> dict[str, Any]:
        """按已配置字段构造登录请求体；不在日志中暴露敏感值。"""

        payload: dict[str, Any] = {}
        if self._username is not None:
            payload["username"] = self._username
        if self._password is not None:
            payload["password"] = self._password
        return payload
