# Market TV Wire

本模块沿用公共 Panel 外壳、布局与 Runtime；不新增频道工作台或采集器。

## 数据与播放契约

- 现有 owner：`scripts/runtime/market_tv_wire_watcher.py`；来源配置与组装归
  `scripts/api/services/live_video_source_service.py`、`live_video_playback_service.py`。
- 原始目录仍由人工配置与有界 IPTV 候选组成；一个频道只有一个选择项，
  `playbackSources` 按序声明 HLS、YouTube 当前直播、固定直播及频道入口。
  同频道失败只切换其备用源，耗尽后显示不可用并允许重试，同时按 1／2／4／5 分钟上限退避自动恢复；隐藏页面不重开流。
  更新当前直播 ID 后可立即重试，不跳到其他频道。
- 人工维护频道优先；Euronews 使用 YouTube 优先。RSS 最新视频不等于直播，
  不用于替代 TV 的当前直播。其他 YouTube 内容面板保留原有资料用途。
- 复用 SQLite `panel_snapshots` 与已配置 Redis：
  `snapshot:content:market-tv-wire / panel-v1`。生产者与 API 读取同一存储身份。
  当前迁移后的 owner 在本机 backend；前端位于腾讯云。旧文档 GCP 位置是历史记录。
- 目录发布/浏览器检查保持 15 分钟；IPTV 原目录每天下载，失败 15 分钟重试，最多保留 7 天的最后有效频道与原获取时间。
  复用 SQLite `source:tv-directory / sha256(feed URL)`，每类最多 480 个、最终仍受 240 项候选总上限约束；失败不会抹掉现有频道。
  YouTube 频道直播 ID 成功后 6 小时再解析，
  失败 15 分钟后重试，最后成功结果最多保留 36 小时且保留原时间。
  固定 YouTube 直播与 HLS 后台例行探测每日一次；失败按 15 分钟恢复。播放器按实际意图即时加载。
- 每轮仍有候选上限与 4 个 HLS 探测线程（每次 HTTP 请求含备用共 12 秒）；频道解析最多 4 并发、单请求含备用共 30 秒。
  不因用户数量新增后台任务，不下载或归档视频。
- 后台探测只说明对应出口可达性。浏览器播放需媒体时钟实际推进，
  YouTube 缓冲、等待开播、回放不能标为正在直播。启动限时 20 秒，播放卡住
  30 秒后尝试同频道下一来源；暂停/隐藏时不判失败，卸载清理请求、播放器和计时器。
- 视频直接使用原站播放器/CDN；受维护的 HLS 可经现有受限转发接口回退。
  后端出口与浏览器网络分别验收。地区限制不通过切换受限国家规避。

## 验证

后端测试验证频道归并、当前直播身份、结束/不可嵌入/解析失败、原时间保留、
独立解析周期；前端测试验证同频道切源、缓冲/回放/实际进度、超时和释放。
发布使用已推送提交的干净构建，并从真实首页检查桌面/手机、频道切换与连续播放。
运行证据写入本索引的验收节，不保留一次性探测脚本和中间报告。

## 参考

WorldMonitor `65860c21` 的 `live-video-sources.ts`、`live-video/model.ts`、
`live-video/session.ts` 及 `seed-live-video-resolved.mjs`。复用其有序候选、真实播放
判断与有界更新思想；继续使用本项目 Python owner、Preact 与既有存储。

已退役且没有已核验备用源的 Reuters TV / The Guardian 从 TV 选择项隐藏；ABC / NBC 仅使用其官方 YouTube 频道，不再反复探测旧 HLS。提高探测超时预算后只重测旧失败结果，成功结果仍复用每日缓存。

欧洲出口的 YouTube 公共 HTML 使用匿名采集 Cookie `SOCS=CAI`，避免进入无直播信息的同意页，依据 [yt-dlp 的匿名初始化](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_base.py)。不读取或保存用户账号 Cookie；登录/访问挑战记为解析失败，不能因此宣布频道停播。

## 最近验收

2026-11-07：按 WorldMonitor 的当前来源表将 CGTN、NHK 的失效域名替换为
官方新 HLS；从 iptv-org 的 news 目录核对 DW 同频道 Amagi 源；真实公网转发播放通过后将其作为优先源，原 Akamai 与 YouTube 保留为同频道备用。
三个地址分别只由 `POLYMONITOR_TV_CGTN_HLS_URL`、
`POLYMONITOR_TV_NHK_HLS_URL`、`POLYMONITOR_TV_DW_HLS_URL` 配置，
缺失配置不回退到旧地址。DW 优先源只允许 `.env` 的 `POLYMONITOR_TV_DW_RESOURCE_PATHS` 明确路径经既有 HLS 转发；307 每一跳复核来源和路径，不放开任意跳转。
不把其他国家版本、活动流或名称相近的 IPTV 条目冒充同频道备用源。

播放器从低码率开始并保留自动升档，只有可见视频尺寸与媒体时钟推进才确认播放；
仅当前直播解析时间变化不重新打开健康流。现有20秒启动、30秒停滞及同频道
退避恢复保持不变。换源验证包括真实片段、Chrome视频帧与时间推进；
生产页面验收与本机媒体预检分别记录，目录数量不作为全频道播放成功数。

2026-11-04 前端 `72ab1f61` 已发布，桌面/手机布局检查及本地同频道切源、缓冲/回放拒绝、自动重试测试通过。
正式直播状态已有 9/12 项解析成功（频道 ID 与固定视频 ID 分别计数，不是 9 个频道）；其余失败按原周期恢复。
最终实播轮仍有主频道未出画面，未完成全部频道连续播放验收。DW 转发已加入实际清单使用的明确备用目录，未放开任意主机或路径。
完整窗口、来源失败与存储核对见 [恢复记录](../../../../../docs/panel-data-recovery-2026-11-04.md)，该窗口不代表未来持续健康。

本轮正式页面实测：CGTN 媒体时间连续推进约30秒、最高1920宽；NHK约45秒、1280宽。DW原Akamai在两个窗口缓冲停滞，播放器依次尝试同频道代理/备用并最终进入YouTube直播；单独实测新Amagi经真实公网API转发约37秒、936解码帧，随后调整为优先源。该证据不是全部240条目录的连续实播验收。
