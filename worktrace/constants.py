APP_NAME = "WorkTrace"
APP_VERSION = "0.1.0"

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

HISTORY_PERSIST_THRESHOLD_SECONDS = 30
DEFAULT_IDLE_THRESHOLD_SECONDS = 5 * 60
DEFAULT_CONTEXT_CARRY_MINUTES = 15
REPORT_CONTEXT_SHORT_MERGE_SECONDS = 5 * 60
DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS = DEFAULT_CONTEXT_CARRY_MINUTES * 60
RULE_CACHE_TTL_SECONDS = 5.0

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
EXCLUDED_PROJECT = "排除规则"

ANCHOR_FILE_EXTENSIONS = (
    ".docx",
    ".doc",
    ".pdf",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".txt",
    ".md",
    ".csv",
)

PRIVACY_NOTICE_TEXT = """WorkTrace 将在本机记录：
- 当前活动应用名称
- 当前窗口标题
- 当前活动文件的完整本地路径（如可识别），用于文件夹规则和项目归类
- 使用开始时间、结束时间和持续时间

WorkTrace 不会记录：
- 键盘输入
- 鼠标点击内容
- 屏幕截图或录屏
- Word、PDF、网页、邮件正文
- 浏览器历史、Cookie 或密码

所有数据默认保存在本机，不上传到云端。文件路径仅保存在本机，用户可通过“清空所有本地记录”删除。

文件路径可能包含用户名、客户名、项目名、案件名等敏感信息；请按需设置排除规则。

排除规则支持文件夹、文件和关键词。关键词会同时匹配应用名称、进程名称、窗口标题和本地文件路径。命中排除规则后，WorkTrace 只记录“已排除窗口”，不会保存真实窗口标题或文件路径。

如果不希望某些客户、案件、文件夹或个人目录被记录，可以在“项目规则”中为“排除规则”添加对应规则。

自动记录只是工作轨迹草稿，最终工时应由用户按需整理和归类。"""
