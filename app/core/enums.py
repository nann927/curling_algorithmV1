"""全局枚举与协议字典。

接口字段、Runtime 状态和赛后结果类型统一放在这里，避免业务代码散落硬编码。
"""

from enum import StrEnum


class ControlAction(StrEnum):
    """IF-01 支持的控制动作。"""

    START = "start"
    UPDATE_CONFIG = "update_config"
    STOP = "stop"


class SceneType(StrEnum):
    """软件平台传入的场景类型。"""

    COMPETITION = "competition"
    PERSONAL_TRAINING = "personal_training"
    TRAINING_CAMP = "training_camp"
    LEAGUE_ACTIVITY = "league_activity"
    STUDY_TOUR = "study_tour"


OVERVIEW_SCENES = {
    # 实时阶段只输出全景，不执行智能切镜；赛后处理仍会保留人员媒体整理入口。
    SceneType.PERSONAL_TRAINING,
    SceneType.TRAINING_CAMP,
    SceneType.LEAGUE_ACTIVITY,
    SceneType.STUDY_TOUR,
}


class StreamType(StrEnum):
    """算法服务对软件平台暴露的实时流类型。"""

    SMART_DIRECTOR = "smart_director"
    OVERVIEW_LIVE = "overview_live"


class RuntimeStatus(StrEnum):
    """MatchRuntime 和 SheetRuntime 的实时任务状态。"""

    RUNNING = "running"
    POST_PROCESSING = "post_processing"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class EditStatus(StrEnum):
    """赛后处理状态，completed 只允许在上传成功后设置。"""

    WAITING = "waiting"
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ResultMode(StrEnum):
    """IF-04 结果组织模式。"""

    MATCHED_HIGHLIGHTS = "matched_highlights"
    LABELED_CLIPS = "labeled_clips"
    PARTICIPANT_MEDIA = "participant_media"


class ResultType(StrEnum):
    """IF-04 具体成品类型。"""

    PLAYER_HIGHLIGHT = "player_highlight"
    TEAM_HIGHLIGHT = "team_highlight"
    LABELED_CLIP = "labeled_clip"
    PARTICIPANT_VIDEO = "participant_video"
    TRAINING_PHOTO = "training_photo"


class DirectionStatus(StrEnum):
    """投壶方向检测状态。"""

    UNKNOWN = "UNKNOWN"
    DETECTING = "DETECTING"
    LOCKED = "LOCKED"
    FROZEN = "FROZEN"


class ThrowStatus(StrEnum):
    """一次投壶 Shot 的主生命周期状态。"""

    IDLE = "IDLE"
    TOUCHED = "TOUCHED"
    RELEASED = "RELEASED"
    PASSED_MAGNETIC_1 = "PASSED_MAGNETIC_1"
    PASSED_MAGNETIC_2 = "PASSED_MAGNETIC_2"
    FINISHED = "FINISHED"


class ShotQualityStatus(StrEnum):
    """Shot 数据质量状态，和主生命周期状态分开维护。"""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    ABNORMAL = "abnormal"
