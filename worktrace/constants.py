APP_NAME = "WorkTrace"
APP_VERSION = "0.1.0"

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

STATUS_NORMAL = "normal"
STATUS_IDLE = "idle"
STATUS_PAUSED = "paused"
STATUS_EXCLUDED = "excluded"
STATUS_ERROR = "error"

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"
SOURCE_SYSTEM = "system"

EXCLUDED_APP_NAME = "已排除"
EXCLUDED_PROCESS_NAME = "excluded"
EXCLUDED_WINDOW_TITLE = "已排除窗口"
UNCATEGORIZED_PROJECT = "未归类"

PRIVACY_NOTICE_TEXT = """WorkTrace 将在本机记录：
- 当前活动应用名称
- 当前窗口标题
- 使用开始时间、结束时间和持续时间

WorkTrace 不会记录：
- 键盘输入
- 鼠标点击内容
- 屏幕截图或录屏
- Word、PDF、网页、邮件正文
- 浏览器历史、Cookie 或密码

所有数据默认保存在本机，不上传到云端。

自动记录只是工作轨迹草稿，最终工时应由用户确认。"""
