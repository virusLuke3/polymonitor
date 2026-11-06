# Politics Panel 设计预览

日期：2026-11-06。主设计与数据覆盖契约：[Politics 方案](../../../docs/politics-panels-design.md)。

这是用户要求的设计交付，所有候选人、议会、数字和事件为**虚构样例**，未接生产 API、未注册生产 Panel、未修改工作台布局。并非已经补齐政治数据。设计文件是保留的交付成果，不是临时探测脚本。

## 查看

通过项目已有 Vite，在 `webpage` 目录运行 `npm run dev -- --host 127.0.0.1 --port 4187`，打开 `/design-previews/politics/`。

默认直接复用当前五列与行高；“展开设计内容”仅增高此预览以便查看，不改变生产默认大小。页签、席位选择、拨款分类、原始口径、Market 规则示例、标题详情/刷新及示例失败/未接入状态可操作。原型中刷新是重置样例状态，Market 展开是接口位置示范，不连接真实合约。

## 设计图

- [原始尺寸 1440px](images/overview-1440.png) / [原始尺寸 2518px](images/overview-2518.png)
- [展开设计全景](images/expanded-2518.png)，仅为查看细节，不是生产尺寸变更。
- [选举相关五个视图](images/row-1.png) / [政府程序五个视图](images/row-2.png)
- [390px 手机全页](images/mobile-390.png) / [手机选举面板](images/mobile-election.png)

| 设计 | 单张图 |
| --- | --- |
| 选举观察 | [民调](images/01-election.png)、[计票](images/election-counting.png)、[认证](images/election-certification.png) |
| 提前投票 | [设计图](images/02-early-vote.png) |
| 提名路径 | [设计图](images/03-nomination.png) |
| 议席格局 | [设计图](images/04-seats.png) |
| 竞选资金 | [设计图](images/05-finance.png) |
| 控制权与组阁 | [设计图](images/06-government.png) |
| 升级 Policy Progress | [设计图](images/07-legislation.png) |
| 行政命令 | [设计图](images/08-executive.png) |
| 政治任命 | [设计图](images/09-appointments.png) |
| 拨款与停摆 | [设计图](images/10-funding.png) |

## 本地设计检查

使用真实项目 Panel、字体、公共 CSS 与 Chrome/Playwright 渲染：

- 10 个面板、11 次不同页签切换、席位和拨款分类选择、Market 示例展开、信息弹层 Escape 关闭、样例刷新重置通过。
- 失败模式保留样例数据；未接入模式移除无意义指标与空图，10 个面板分别说明范围缺失。
- 2518px：5 列，每列约 498.8px，默认行高282px；1440px：5列，每列约283.2px，默认行高268px。
- 390/375px：单列；没有页面或 Panel 正文横向溢出。手机席位使用原生选择器，避免要求精确点击细小格子。
- 无页面未捕获 JS 错误；没有业务 API 请求。只验证设计交互，不作为采集、生产或自动更新验收。
- 首次2518px截图遇到Chrome截图失败；禁用GPU后完成截图。未通过修改页面内容或替换业务API掩盖错误。

视觉借鉴来自仓库已有 WorldMonitor 实图，记录于[参考说明](../external-panels/worldmonitor-reference/README.md)。本次查看并使用分类大数字、浅色强调块、不同类别色与图形组合；不再把正文统一为同色小字列表。
