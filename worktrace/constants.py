APP_NAME = "WorkTrace"
APP_VERSION = "0.1.0"

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Deprecated compatibility shape only. Raw collector activity has no
# persistence threshold and production code must not read this value.
HISTORY_PERSIST_THRESHOLD_SECONDS = 0
# Deprecated compatibility constant. Project display no longer waits or
# inherits an earlier project while a candidate is confirmed.
PROJECT_OWNERSHIP_CONFIRM_SECONDS = 0
DEFAULT_IDLE_THRESHOLD_SECONDS = 5 * 60
DEFAULT_CONTEXT_CARRY_MINUTES = 15
REPORT_CONTEXT_SHORT_MERGE_SECONDS = 5 * 60
DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS = DEFAULT_CONTEXT_CARRY_MINUTES * 60
RULE_CACHE_TTL_SECONDS = 5.0
CLIPBOARD_RETENTION_DAYS = 30
CLIPBOARD_TRANSITION_SECONDS = 10

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
- 当前活动应用名称、进程名称、窗口标题
- 可识别的本地文件路径（如 Word、Excel、PPT、PDF、代码文件等），用于文件夹规则和项目归类
- 浏览器标签页标题和可见域名（如能从窗口标题识别）
- 邮件标题或邮件文件名（如能从窗口标题/文件名识别）
- IDE 文件名、路径或工作区名（如能识别）
- 已绑定文件夹规则下的文件名与完整路径索引（仅本机派生缓存）
- 使用开始时间、结束时间和持续时间
- 开启"记录复制文字"后，复制到剪贴板的文本内容（默认关闭，最多保留 30 天）

WorkTrace 不会记录：
- 邮件正文
- 网页正文
- Word、PDF、Excel、代码文件正文
- 浏览器历史、Cookie 或密码
- 键盘输入
- 鼠标点击内容
- 屏幕截图或录屏

所有数据默认保存在本机，不上传到云端。文件路径和复制文字仅保存在本机，用户可通过"清空所有本地记录"删除。
文件夹索引不读取文件内容；它只保存文件名和完整路径，用于窗口标题只有文件名时反查项目规则。
复制文字记录默认关闭；开启后用于关键词归类和后续本地工作描述生成，WorkTrace 会自动清理 30 天前的复制文字。

文件路径和复制文字可能包含用户名、客户名、项目名、案件名等敏感信息；请按需设置排除规则，并只在需要时开启复制文字记录。

排除规则支持文件夹和关键词。关键词会同时匹配应用名称、进程名称、窗口标题和本地文件路径。命中排除规则后，WorkTrace 只记录"已排除窗口"，不会保存真实窗口标题、文件路径、邮件标题、浏览器域名或 IDE 信息。

如果不希望某些客户、案件、文件夹或个人目录被记录，可以在"项目规则"中为"排除规则"添加对应规则。

自动记录只是工作轨迹草稿，最终工时应由用户按需整理和归类。"""
