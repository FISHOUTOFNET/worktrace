# WorkTrace UI 设计系统

## 1. 产品视觉定位

WorkTrace 是本地 Windows 时间记录生产力工具。界面应专业、克制、可信，以清楚的时间、项目、描述和活动事实为中心。视觉语言参考 Windows 11 桌面软件，但不复制系统控件：中性灰白背景、少量蓝色强调、中等信息密度，主要通过间距、字重、分隔线和表面层级组织内容。

设计系统只服务当前五个页面，不建立主题框架、通用组件库或动画系统。所有资源随应用本地打包，不使用网络字体、远程图标或浏览器存储。

## 2. Foundation 与 tokens

正式 CSS 使用下列命名，原型使用相同数值。页面样式不得重新定义同义 token。

### 2.1 字体与数字

```css
--font-sans: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei", sans-serif;
--font-size-xs: 11px;
--font-size-sm: 12px;
--font-size-md: 13px;
--font-size-lg: 15px;
--font-size-xl: 20px;
--font-size-2xl: 24px;
--line-height-tight: 1.25;
--line-height-normal: 1.45;
```

- 正文为 13px；辅助信息为 12px；徽标为 11px。
- 页面标题为 20px / 650；区块标题为 15px / 650。
- 关键时长为 24px / 650，摘要时长为 18px / 650。
- 时间、时长、计数与百分比统一使用 `font-variant-numeric: tabular-nums`。
- 不使用远程字体或自定义图标字体。

### 2.2 颜色

```css
--color-canvas: #eef2f5;
--color-nav: #f7f9f8;
--color-surface: #ffffff;
--color-surface-subtle: #f4f7f8;
--color-surface-selected: #e3eff8;
--color-surface-hover: #edf3f7;
--color-text: #17232b;
--color-text-secondary: #53636d;
--color-text-tertiary: #7b8991;
--color-border: #d3dce2;
--color-border-strong: #aebbc4;
--color-accent: #226da8;
--color-accent-hover: #175b91;
--color-accent-soft: #e3eff8;
--color-success: #2c7656;
--color-success-soft: #e6f3ec;
--color-warning: #8a6114;
--color-warning-soft: #fff5da;
--color-danger: #ba352f;
--color-danger-hover: #9d2925;
--color-danger-soft: #fff0ee;
--color-scrim: rgba(21, 31, 38, .38);
--color-focus: #1769aa;
```

颜色只辅助表达。当前导航同时使用 `aria-current` 和左侧强调条；进行中包含状态点和文字；危险操作具有明确文案；选中行具有边框、背景和选中语义。

### 2.3 间距与尺寸

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
--control-height-sm: 28px;
--control-height: 30px;
--control-height-lg: 34px;
--page-padding-x: 18px;
--page-padding-y: 15px;
--radius-sm: 3px;
--radius-md: 4px;
--radius-lg: 6px;
--border-width: 1px;
--shadow-flyout: 0 10px 30px rgba(24, 35, 43, .16);
--shadow-dialog: 0 18px 52px rgba(24, 35, 43, .22);
--focus-ring: 0 0 0 2px var(--color-surface), 0 0 0 4px var(--color-focus);
```

- 标准页面横向边距 18px、纵向边距 15px；紧凑窗口横向 14px、纵向 12px。
- 默认控件高 30px，主要按钮可用 34px，紧凑工具按钮可用 28px；输入框保持 13px 字号，通过减少内边距控制密度。
- 普通表面无阴影；只有 Drawer、Dialog、Menu、Toast 使用阴影。
- 圆角以 4px 为主，外层工作区最多 6px，不使用胶囊形大面积容器。

### 2.4 响应式断点

- `>= 960px`：188px 标准导航，Timeline 双栏。
- `< 960px`：56–64px rail，Timeline Inspector 改为覆盖 Drawer。
- `< 720px`：工具栏允许分两行，Overview 单栏，Statistics 摘要两列。
- 内容最大宽度 1440px；大屏不无限拉伸。
- 页面本身不得横向滚动；宽表只允许在 `.table-scroll` 内横向滚动。

Windows 125% 和 150% 缩放通过相同响应式规则适配，不建立缩放专用分支。

## 3. 控件

### 3.1 Button

- `primary`：每个局部区域最多一个，蓝底白字。
- `secondary`：白底边框，用于普通操作。
- `subtle`：透明背景，用于低频或邻近操作。
- `danger`：白底红字红边；最终确认可用红底白字。
- 文案使用具体动词，如“删除时间段”“导出 CSV”，不使用含糊的“确定”。
- loading 时保留按钮宽度；禁用不只降低透明度，还设置 `disabled`。

### 3.2 IconButton

- 固定 30×30px，紧凑操作可用 28×28px，统一使用一个本地内联 SVG sprite。
- 必须提供 `aria-label` 与 Tooltip；装饰 SVG 使用 `aria-hidden="true"`。
- 不使用第三方品牌图标，不为页面建立独立图标体系。

### 3.3 Input、Select、Textarea

- 高 30px，边框 1px，圆角 4px；Textarea 最小高 68px，可纵向缩放。
- 标签始终可见；placeholder 不代替标签。
- 错误在字段附近显示并使用明确文案；无效值不提交。
- 用户描述为空时，派生摘要可作为 placeholder，但不会写入 value。

### 3.4 Checkbox 与 Toggle

- Checkbox 用于独立选择，如“同时应用到历史记录”。
- Toggle 只用于立即生效的二元设置，如剪贴板采集。
- 控件和文字共享同一可点击标签，提供 `checked` / `disabled` 原生语义。
- 新文件夹规则固定包含子文件夹，因此 UI 不显示对应 Toggle。

## 4. 布局组件

### 4.1 Page Header

包含页面标题、可选的一行说明和真正必要的主操作。自动刷新页面不放普通刷新按钮。标题区与工具栏分离。

### 4.2 Toolbar

使用 6px 间距、浅色表面和完整 1px 边界，可在窄窗口分行。过滤条件有显式标签，状态与总计靠右但不得被挤出可视区。

### 4.3 Surface 与 Section

- `Surface` 用于一个完整工作区或需要边界的列表，不是默认包装。
- `Section` 优先使用留白、标题和分隔线。
- 同一屏幕避免卡片套卡片和五个等权 KPI 卡片。

### 4.4 Table

- 表头 12px / 600、浅灰背景；行高约 40px。
- 数字列右对齐并使用等宽数字；名称列允许截断且有 `title`。
- 空状态替换表体，不保留空白大表格。

### 4.5 Tabs

用于 Statistics 的“按项目 / 按应用”和 Drawer 内有限的规则类型。当前 Tab 使用下边框、字重和 `aria-selected`，支持左右方向键。

### 4.6 Badge

只表达短状态，例如“进行中”“自动摘要”。高度 20px，不能成为主要按钮，也不能只靠颜色表达含义。

## 5. 反馈组件

### 5.1 Inline Alert

用于需要用户处理的错误、警告或阻断。错误使用 `role="alert"`；成功不使用错误 Banner。保留旧数据时 Alert 位于相关区域上方。

### 5.2 Inline Status

用于“更新中…”“保存中…”“已保存”等局部状态。使用 `role="status"` 或节制的 `aria-live="polite"`；每秒 LiveClock 节点必须保持 `aria-live="off"`。

### 5.3 Toast

只用于完成后无需持续保留的轻量反馈。右下角显示，自动消失但允许关闭；错误若需要处理则使用 Inline Alert。

### 5.4 Skeleton

首次加载只保留页面框架并显示少量静态骨架；自动刷新继续显示已接受数据，不重新展示 Skeleton。

### 5.5 Empty State

包含一句结论、一句说明和最多一个合理操作。不要用插图填空，也不要保留大型空卡片。

## 6. 浮层

### 6.1 Drawer

- 从右侧覆盖，宽度 400–440px，最大不超过主工作区；800×540 下使用 `min(430px, calc(100% - 8px))`。
- 打开时记录触发器，设置初始焦点并限制 Tab 焦点；Escape、关闭按钮和遮罩可关闭。
- 关闭后恢复触发器焦点；Drawer 自己滚动，页面保持稳定。
- Timeline 紧凑编辑、项目新建/编辑、规则新建/编辑共享同一基础设施。

### 6.2 Dialog

- 使用 `role="dialog" aria-modal="true"` 与明确标题。
- 初始焦点通常在取消按钮；危险第二步初始焦点仍不放在最终删除按钮。
- Tab 焦点限制、Escape 关闭、关闭后恢复触发器焦点。

### 6.3 两步删除确认

时间段和活动删除使用同一 Dialog 的两个步骤：

1. 明确对象、影响和不可撤销性，操作为“取消 / 继续”。
2. 再次显示稳定目标，操作为“返回 / 确认删除时间段（或活动）”。

第一步不写数据；最终 pending 时不提前移除；failed / unknown 保留目标并显示对应状态。项目删除按后端真实影响提供一次或两步确认，禁止 `window.confirm`。

## 7. 内容语义

### 7.1 自动保存状态

状态为 dirty、saving、saved、failed、unknown：

- 描述在停止输入 500–800ms 后提交；项目立即提交；时长在有效输入完成后提交。
- 较早响应不能覆盖较新输入；failed / unknown 保留输入。
- generation 变化使旧草稿失效；切换时间段前安全处理 pending edit。
- “已保存”短暂出现，不提供保存/取消按钮。

### 7.2 用户描述与自动摘要

- 用户描述为主文本。
- 自动摘要使用次级文本，并显示“自动摘要”标签，不能只通过颜色区分。
- “暂无描述”使用次级文本。
- 自动摘要只展示，不写入用户描述、不触发保存、不进入用户描述导出。

### 7.3 危险操作

危险操作与普通操作空间上分组、视觉上使用红色、文案上说明对象。常用删除入口直接可见；数据库替换和清空继续使用确认文字，不能降级为普通 Dialog。

## 8. 键盘与可访问性

- 全局交互元素使用统一 `:focus-visible` ring，不移除浏览器焦点而不给替代样式。
- 主导航当前项设置 `aria-current="page"`；紧凑 rail 保留 Tooltip 与 accessible name。
- Timeline 行使用 button / option 等价语义；上下键按视觉顺序移动，Enter / Space 选择。
- Escape 关闭 Drawer、Dialog 和 Menu；关闭后恢复焦点。
- 动态错误使用 `role="alert"`，局部保存状态使用节制的 `aria-live`。
- 图标按钮具有 accessible name；Tooltip 不承载唯一信息。
- 长中文文本与长项目名允许截断，但通过 `title` 或可访问文本保留完整内容。
- 进行中、危险、选中、用户描述与自动摘要均不得只通过颜色区分。
- 尊重 `prefers-reduced-motion`；所有必要交互不依赖动画。

## 9. CSS 组织

正式应用保留一个本地 `styles.css`，按固定顺序组织：

1. foundation / tokens / reset；
2. app shell / layout；
3. shared components；
4. page-specific styles（Timeline、Overview、Rules、Statistics、Settings）；
5. responsive rules；
6. small utilities。

不允许文件尾部再次覆盖同名组件定义，不依赖高 specificity 或加载顺序修复页面差异。页面专用选择器以页面根类为边界，共享控件不复制实现。
