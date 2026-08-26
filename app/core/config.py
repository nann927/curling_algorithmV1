"""配置加载模块。

业务代码只能通过 get_config_manager/get_settings 读取配置，避免到处直接读取环境变量或 JSON 文件。
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ARRAY_CAMERA_ROLES = {"medium_shot", "close_shot"}
OVERVIEW_INSTALL_ENDS = {"overview_A": "A", "overview_B": "B"}


class Settings(BaseSettings):
    """运行配置。

    `.env` 中的字段使用 CURLING_ 前缀；固定业务配置来自 system_config.json。
    """

    app_env: str = "development"
    mock_mode: bool = False
    public_base_url: str = "http://localhost:8000"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=list)
    system_config_path: str = "config/system_config.json"
    site_config_path: str = "config/site_config.json"
    integration_mock_path: str = "config/integration_mock.json"
    sqlite_path: str = "data/db/curling.db"
    log_path: str = "data/logs/app.log"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ws_enabled: bool = False
    api_base_url: str = ""
    ws_url: str = ""
    login_path: str = "/sys/mLogin"
    username: str | None = None
    password: str | None = None
    user_id: str | None = None
    ws_reconnect_seconds: float = 3.0
    ws_connect_timeout_seconds: float = 5.0
    position_cache_size: int = 20
    position_freshness_ms: int = 1000
    direction_confirm_count: int = 3
    system_config: dict[str, Any] = Field(default_factory=dict)
    site_config: dict[str, Any] = Field(default_factory=dict)
    integration_mock_config: dict[str, Any] = Field(default_factory=dict)

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CURLING_", extra="ignore")
    @field_validator("position_cache_size", "position_freshness_ms")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        """缓存长度和 freshness 窗口必须为正数，避免方向判断永远失效。"""

        if value <= 0:
            raise ValueError("value must be greater than 0")
        return value

    @field_validator("direction_confirm_count")
    @classmethod
    def validate_direction_confirm_count(cls, value: int) -> int:
        """方向锁定至少需要 1 个定位点参与确认。"""

        if value < 1:
            raise ValueError("direction_confirm_count must be greater than or equal to 1")
        return value


class CoordinateBoundsConfig(BaseModel):
    """场地矩形区域配置，坐标单位沿用电子冰壶系统原始坐标。"""

    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None


class PhysicalHoglineConfig(BaseModel):
    """固定物理 hog line 坐标；按 A/B 端命名，避免混淆协议中的 hogline1/2 顺序。"""

    x: float | None = None
    y: float | None = None


class SheetPositionCalibrationConfig(BaseModel):
    """单条赛道定位标定配置；现场未标定时允许字段为 null。"""

    sheet_id: str
    enabled: bool = False
    position_lane_id: str | None = None
    lane_bounds: CoordinateBoundsConfig | None = None
    ready_zones: dict[str, CoordinateBoundsConfig | None] = Field(default_factory=lambda: {"A": None, "B": None})
    hoglines: dict[str, PhysicalHoglineConfig | None] = Field(default_factory=lambda: {"A": None, "B": None})

    @field_validator("ready_zones", "hoglines")
    @classmethod
    def validate_end_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        """标定端位只允许 A/B；字段缺失表示尚未现场标定。"""

        invalid = set(value) - {"A", "B"}
        if invalid:
            raise ValueError(f"calibration end keys must be A/B, invalid={sorted(invalid)}")
        return value


class SiteCalibrationConfig(BaseModel):
    """现场标定配置根节点；Phase 7.1 只建模型，不推导方向。"""

    position: list[SheetPositionCalibrationConfig] = Field(default_factory=list)


class SiteSheetConfig(BaseModel):
    """现场赛道配置。"""

    sheet_id: str
    sheet_name: str | None = None
    preview_url: str | None = None
    enabled: bool = True
    position_lane_id: str | None = None
    trigger_lane_id: str | None = None
    direction_zones: dict[str, Any] = Field(default_factory=lambda: {"A": None, "B": None})


class SiteLaneMapping(BaseModel):
    """电子冰壶 lane_id 到 sheet_id 的映射。"""

    lane_id: str
    sheet_id: str


class StoneRegistryConfig(BaseModel):
    """冰壶石头注册表配置。

    真实 tag_id 尚未提供时允许为 null；现场补齐后只改 JSON。
    """

    stone_id: str
    tag_id: str | None = None


class SiteCameraConfig(BaseModel):
    """现场摄像头配置。

    真实 IP、账号、Token 不写入本模型；敏感信息后续从 .env 读取。
    """

    camera_id: str
    camera_role: str
    sheet_id: str | None = None
    install_end: str | None = None
    source_provider: str
    description: str | None = None
    source_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("install_end")
    @classmethod
    def validate_install_end(cls, value: str | None) -> str | None:
        """安装端位只能是 A/B/null。"""

        if value not in (None, "A", "B"):
            raise ValueError("install_end must be A, B or null")
        return value


class SiteMicrophoneConfig(BaseModel):
    """现场麦克风配置占位，当前允许 provider/source_config 为空。"""

    microphone_id: str
    sheet_id: str | None = None
    install_end: str | None = None
    source_provider: str | None = None
    source_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("install_end")
    @classmethod
    def validate_install_end(cls, value: str | None) -> str | None:
        """安装端位只能是 A/B/null。"""

        if value not in (None, "A", "B"):
            raise ValueError("install_end must be A, B or null")
        return value


class SiteConfig(BaseModel):
    """现场设备配置。

    该配置用于把 camera_id、sheet_id、lane_id 和 provider 参数从业务代码中剥离。
    """

    site_id: str
    sheets: list[SiteSheetConfig] = Field(default_factory=list)
    lane_mappings: list[SiteLaneMapping] = Field(default_factory=list)
    cameras: list[SiteCameraConfig] = Field(default_factory=list)
    microphones: list[SiteMicrophoneConfig] = Field(default_factory=list)
    stone_registry: list[StoneRegistryConfig] = Field(default_factory=list)
    calibration: SiteCalibrationConfig = Field(default_factory=SiteCalibrationConfig)

    @model_validator(mode="after")
    def validate_site_config(self) -> "SiteConfig":
        """校验现场配置引用关系和重复 ID。"""

        supported_providers = {"local_file", "fusion_server", "rtsp"}
        sheet_id_values = [sheet.sheet_id for sheet in self.sheets]
        sheet_ids = set(sheet_id_values)
        if len(sheet_ids) != len(self.sheets):
            raise ValueError(f"sheet_id must be unique, duplicates={_duplicates(sheet_id_values)}")

        position_lane_ids = [sheet.position_lane_id for sheet in self.sheets if sheet.position_lane_id]
        if len(set(position_lane_ids)) != len(position_lane_ids):
            raise ValueError(f"position_lane_id must be unique, duplicates={_duplicates(position_lane_ids)}")

        trigger_lane_ids = [sheet.trigger_lane_id for sheet in self.sheets if sheet.trigger_lane_id]
        if len(set(trigger_lane_ids)) != len(trigger_lane_ids):
            raise ValueError(f"trigger_lane_id must be unique, duplicates={_duplicates(trigger_lane_ids)}")

        camera_ids = [camera.camera_id for camera in self.cameras]
        if len(set(camera_ids)) != len(camera_ids):
            raise ValueError(f"camera_id must be unique, duplicates={_duplicates(camera_ids)}")

        lane_ids = [mapping.lane_id for mapping in self.lane_mappings]
        if len(set(lane_ids)) != len(lane_ids):
            raise ValueError(f"lane_id mapping must be unique, duplicates={_duplicates(lane_ids)}")

        mapped_sheets = [mapping.sheet_id for mapping in self.lane_mappings]
        if len(set(mapped_sheets)) != len(mapped_sheets):
            raise ValueError(f"one sheet_id cannot be mapped by multiple lane_id values, duplicates={_duplicates(mapped_sheets)}")

        for mapping in self.lane_mappings:
            if mapping.sheet_id not in sheet_ids:
                raise ValueError(f"lane mapping references unknown sheet_id: {mapping.sheet_id}")

        for camera in self.cameras:
            if camera.source_provider not in supported_providers:
                raise ValueError(f"unsupported source_provider: {camera.source_provider}")
            if camera.sheet_id is not None and camera.sheet_id not in sheet_ids:
                raise ValueError(f"camera references unknown sheet_id: {camera.sheet_id}")

        for microphone in self.microphones:
            if microphone.sheet_id is not None and microphone.sheet_id not in sheet_ids:
                raise ValueError(f"microphone references unknown sheet_id: {microphone.sheet_id}")

        stone_ids = [stone.stone_id for stone in self.stone_registry]
        if len(set(stone_ids)) != len(stone_ids):
            raise ValueError(f"stone_id must be unique, duplicates={_duplicates(stone_ids)}")

        tag_ids = [stone.tag_id for stone in self.stone_registry if stone.tag_id]
        if len(set(tag_ids)) != len(tag_ids):
            raise ValueError(f"tag_id must be unique when not null, duplicates={_duplicates(tag_ids)}")

        calibration_sheet_ids = [item.sheet_id for item in self.calibration.position]
        if len(set(calibration_sheet_ids)) != len(calibration_sheet_ids):
            raise ValueError(f"calibration sheet_id must be unique, duplicates={_duplicates(calibration_sheet_ids)}")
        for calibration in self.calibration.position:
            if calibration.sheet_id not in sheet_ids:
                raise ValueError(f"calibration references unknown sheet_id: {calibration.sheet_id}")
        return self


class IntegrationPostProcessConfig(BaseModel):
    """Integration Mock 赛后处理节奏配置。"""

    enabled: bool = True
    processing_duration_seconds: float = 6.0
    progress_points: list[dict[str, float | int]] = Field(
        default_factory=lambda: [
            {"seconds": 0, "progress": 20},
            {"seconds": 2, "progress": 60},
            {"seconds": 4, "progress": 90},
            {"seconds": 6, "progress": 100},
        ]
    )


class IntegrationSheetMediaConfig(BaseModel):
    """Integration Mock 单条赛道测试媒体配置。

    preview_url 和 media_url 只用于联调播放器切流验证；为空时继续走 PUBLIC_BASE_URL fallback。
    """

    preview_url: str | None = None
    media_url: str | None = None


class IntegrationMockConfig(BaseModel):
    """公网联调 Mock 配置。"""

    enabled: bool = False
    sheets: list[str] = Field(default_factory=list)
    sheet_media: dict[str, IntegrationSheetMediaConfig] = Field(default_factory=dict)
    postprocess: IntegrationPostProcessConfig = Field(default_factory=IntegrationPostProcessConfig)
    mock_media: dict[str, Any] = Field(default_factory=lambda: {"enabled": True, "stream_format": "m3u8"})


class ConfigManager:
    """统一配置管理器。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.site_config = SiteConfig.model_validate(settings.site_config)
        self.integration_mock_config = IntegrationMockConfig.model_validate(settings.integration_mock_config)


    def get_sheet(self, sheet_id: str) -> SiteSheetConfig:
        """按 sheet_id 获取赛道配置。"""

        for sheet in self.site_config.sheets:
            if sheet.sheet_id == sheet_id:
                return sheet
        raise KeyError(f"sheet_id not found in site_config: {sheet_id}")

    def get_overview_camera_ids(self) -> list[str]:
        """读取软件侧可选择的阵列逻辑 ID。"""

        return [camera.camera_id for camera in self.site_config.cameras if camera.camera_role == "overview"]

    def get_overview_install_end(self, overview_id: str) -> str:
        """把 overview_A/overview_B 映射为 A/B 端位；非法逻辑 ID 必须显式拒绝。"""

        if overview_id not in OVERVIEW_INSTALL_ENDS:
            raise ValueError(f"unsupported overview camera: {overview_id}")
        camera = self.get_camera(overview_id)
        if camera.camera_role != "overview":
            raise ValueError(f"camera is not overview logical camera: {overview_id}")
        return OVERVIEW_INSTALL_ENDS[overview_id]

    def get_array_cameras(self, sheet_id: str, overview_id: str) -> list[SiteCameraConfig]:
        """按 sheet_id 和 overview_A/B 展开当前赛道对应端位的阵列内部细分镜头。

        阵列内部只包含 medium_shot、close_shot 等角色；house_top 是独立大本营俯拍，不在这里自动加入。
        """

        install_end = self.get_overview_install_end(overview_id)
        return [
            camera
            for camera in self.get_sheet_cameras(sheet_id, install_end=install_end)
            if camera.camera_role in ARRAY_CAMERA_ROLES
        ]

    def get_house_camera(self, sheet_id: str, camera_id: str) -> SiteCameraConfig:
        """校验并返回软件显式选择的单路大本营俯拍摄像头。"""

        camera = self.get_camera(camera_id)
        if camera.sheet_id != sheet_id:
            raise ValueError(f"house camera does not belong to sheet: {camera_id}")
        if camera.camera_role != "house_top":
            raise ValueError(f"camera is not house_top: {camera_id}")
        return camera

    def get_camera(self, camera_id: str) -> SiteCameraConfig:
        """按 camera_id 获取现场摄像头配置。"""

        for camera in self.site_config.cameras:
            if camera.camera_id == camera_id:
                return camera
        raise KeyError(f"camera_id not found in site_config: {camera_id}")
    def get_sheet_cameras(
        self,
        sheet_id: str,
        *,
        camera_role: str | None = None,
        install_end: str | None = None,
    ) -> list[SiteCameraConfig]:
        """按赛道、镜头角色和端位查询摄像头。

        后续 DirectorService 做切镜时只调用本方法，不直接遍历 JSON。
        """

        self.validate_sheet_id(sheet_id)
        cameras = [camera for camera in self.site_config.cameras if camera.sheet_id == sheet_id]
        if camera_role is not None:
            cameras = [camera for camera in cameras if camera.camera_role == camera_role]
        if install_end is not None:
            cameras = [camera for camera in cameras if camera.install_end == install_end]
        return cameras

    def get_sheet_camera_ids_by_role(self, sheet_id: str) -> dict[str, list[str]]:
        """返回某条赛道下按镜头角色分组的 camera_id。"""

        grouped: dict[str, list[str]] = {}
        for camera in self.get_sheet_cameras(sheet_id):
            grouped.setdefault(camera.camera_role, []).append(camera.camera_id)
        return grouped

    def get_overview_camera_id(self, requested_camera_ids: list[str]) -> str:
        """从软件传入的全景摄像头列表中选择第一路有效 camera_id。"""

        if not requested_camera_ids:
            raise ValueError("overview_cameras must not be empty")
        self.get_camera(requested_camera_ids[0])
        return requested_camera_ids[0]

    def validate_sheet_id(self, sheet_id: str) -> None:
        """校验 sheet_id 是否存在于现场配置。"""

        if sheet_id not in {sheet.sheet_id for sheet in self.site_config.sheets}:
            raise ValueError(f"sheet_id not found in site_config: {sheet_id}")

    def get_sheet_id_by_position_lane(self, lane_id: str) -> str:
        """将定位平台 laneId 转换为内部 sheet_id。"""

        for mapping in self.site_config.lane_mappings:
            if mapping.lane_id == lane_id:
                return mapping.sheet_id
        for sheet in self.site_config.sheets:
            if sheet.position_lane_id == lane_id:
                return sheet.sheet_id
        raise KeyError(f"position_lane_id not found in site_config: {lane_id}")

    def get_position_calibration(self, sheet_id: str) -> SheetPositionCalibrationConfig:
        """读取单条赛道定位标定；未配置时返回未标定模型。"""

        self.validate_sheet_id(sheet_id)
        for calibration in self.site_config.calibration.position:
            if calibration.sheet_id == sheet_id:
                return calibration
        sheet = self.get_sheet(sheet_id)
        return SheetPositionCalibrationConfig(sheet_id=sheet_id, enabled=False, position_lane_id=sheet.position_lane_id)

    def get_sheet_id_by_trigger_lane(self, lane_id: str) -> str:
        """将触发平台 laneId 转换为内部 sheet_id。"""

        for sheet in self.site_config.sheets:
            if sheet.trigger_lane_id == lane_id:
                return sheet.sheet_id
        raise KeyError(f"trigger_lane_id not found in site_config: {lane_id}")

    def get_direction_zones(self, sheet_id: str) -> dict[str, Any]:
        """读取赛道 A/B 发球区配置。"""

        self.validate_sheet_id(sheet_id)
        for sheet in self.site_config.sheets:
            if sheet.sheet_id == sheet_id:
                return sheet.direction_zones
        return {"A": None, "B": None}


def _read_json_file(path: str) -> dict[str, Any]:
    """读取 JSON 文件；空文件按空对象处理。"""

    config_path = Path(path)
    if not config_path.exists() or not config_path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def _apply_plain_env(settings: Settings) -> Settings:
    """兼容无 CURLING_ 前缀的部署环境变量。

    公网联调文档使用 APP_ENV/MOCK_MODE/PUBLIC_BASE_URL 等名称；这里显式覆盖，避免破坏原有
    CURLING_ 前缀配置。
    """

    plain_env_map = {
        "APP_ENV": ("app_env", str),
        "MOCK_MODE": ("mock_mode", _to_bool),
        "PUBLIC_BASE_URL": ("public_base_url", str),
        "HOST": ("host", str),
        "PORT": ("port", int),
        "CORS_ORIGINS": ("cors_origins", _to_list),
        "SYSTEM_CONFIG_PATH": ("system_config_path", str),
        "SITE_CONFIG_PATH": ("site_config_path", str),
        "INTEGRATION_MOCK_PATH": ("integration_mock_path", str),
    }
    for env_name, (field_name, caster) in plain_env_map.items():
        if env_name in os.environ:
            setattr(settings, field_name, caster(os.environ[env_name]))
    return settings


def _duplicates(values: list[str]) -> list[str]:
    """返回列表中的重复值。"""

    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _to_bool(value: str) -> bool:
    """解析布尔环境变量。"""

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_list(value: str) -> list[str]:
    """解析逗号分隔环境变量。"""

    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """加载并缓存配置，避免重复解析 JSON。"""

    settings = Settings()
    settings = _apply_plain_env(settings)
    settings.system_config = _read_json_file(settings.system_config_path)
    settings.site_config = _read_json_file(settings.site_config_path)
    settings.integration_mock_config = _read_json_file(settings.integration_mock_path)
    return settings


@lru_cache
def get_config_manager() -> ConfigManager:
    """加载并缓存 ConfigManager。"""

    return ConfigManager(get_settings())
