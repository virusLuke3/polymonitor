# World Event Map v1 / Natural Hazards v1.1 交付报告

> 验收日期：2026-07-29  
> 分支：`codex/world-event-map-implementation`  
> 指导契约：`docs/world-event-map-implementation-guide.md`

## 1. 产品结果

2D 地图已经从“天气 Polymarket 城市与市场的空间入口”改为 World Event Map：

- 默认主体是真实自然灾害：强风暴、飓风/热带气旋、洪水、极端温度警报、地震、火山、野火和有定量依据的重大气象异常。
- Polymarket 市场不生成地图 marker、polygon 或覆盖范围。
- 只有选中自然灾害后，Inspector 才按类型、空间、时间和结算指标四维证据加载 Related Weather Markets。
- Intel Hotspots、Conflict & Unrest、Sanctions & Country Risk 是真实的可选图层，默认关闭。
- UCDP、航空参考数据和国家风险不会改变自然灾害作为默认地图主体的产品语义。

当前不存在声明可用但没有渲染实现的地图图层。`Heatmap`、`Risk Density` 等伪模式没有进入新的 MapState。

## 2. 数据与证据契约

### Natural Hazards

- USGS：地震。
- NASA EONET：热带气旋、洪水、火山、命名火灾与灾害发现事件。
- NWS CAP/API：美国及其责任区的强风暴、洪水、极端温度等官方警报。
- FIRMS：只有配置数据源后才展示卫星热异常；未配置时显示 coverage gap。
- Climate anomaly：只有同时具有变量、数值、单位、baseline period 和 calculation version 才能进入地图；未配置定量管线时不伪造异常。

### Intel Hotspots

Intel 国家面必须同时满足：

1. 能映射到本地 ISO 国家几何，不能是 `Global` 或未知实体；
2. 有有效事件时间；
3. confidence 不低于 0.60；
4. 至少两篇文章，且来源多样性不低于 2。

低置信 Wikimedia pageview proxy、无法解析的国家和弱单源新闻会进入 rejected 计数，不会上图。

### Sanctions & Country Risk

后端分别输出：

- `sanctionsTargetBreakdown`：OFAC / Federal Register 证据；
- `countryRiskBreakdown`：UCDP / 已验证冲突源聚合。

前端按 ISO 国家合并详情，但保留 `sanctionsEvidenceCount` 与 `countryRiskEvidenceCount` 两个独立字段，不相加、不互相冒充。国家级记录只渲染本地 GeoJSON polygon；未知实体和 `ISRAEL / GAZA` 这类复合区域不会被错误映射到首都或单一国家。

旧 `targetBreakdown` 缓存仍可读取，但被标记为 `geo-shock-legacy-mixed`，只能作为国家风险证据，不会被称作制裁数量。

## 3. 解耦与鲁棒性

- `GeoEvent` / `HazardEvent` 是 renderer 唯一接收的事件模型。
- 图层声明统一位于 layer registry；MapState 统一控制 camera、region、layers、time、severity 和 selection，并序列化到 URL。
- 数据 adapter、国家身份解析、国家几何加载、source status、renderer、Inspector 和 market linker 分层实现。
- Deck/WebGL 与 SVG 实现同一 renderer interface；软件 WebGL、初始化失败或 context loss 可切换 SVG。
- 单个 provider 超时不会清空其他来源；刷新失败保留 stale 数据并显示逐来源状态。
- 请求有 timeout、AbortController、竞态抑制和有界重试。
- 页面隐藏或地图离屏时暂停持续工作；mount/unmount 清理 listener、observer、timer 和 renderer。
- Supercluster、viewport buffer、zoom disclosure、标签阈值和 300 条可访问事件列表上限控制全局视图密度。
- Inspector 统一展示来源、freshness、置信度、限制和类别专属证据；只有 HazardEvent 渲染 Related Weather Markets。

## 4. 自动化验证

最终变更执行：

```text
webpage npm run test:map
  51 passed, 1 skipped

pytest -q tests/test_geo_sanctions_shock.py \
  tests/test_global_transport_shipping_panel.py \
  tests/test_weather_panels.py
  47 passed

webpage npm run build
  locale contract, TypeScript and Vite production build passed
```

地图测试覆盖 2,000 事件 fixture、聚类、URL 状态、adapter/validation、SVG polygon winding、软件 WebGL 检测、可访问事件列表和数据失败状态。浏览器测试覆盖桌面、390×844 移动视口、URL 图层恢复、国家面点击、Inspector focus/内容、弱 Intel 拒绝、相关市场边界、无横向溢出和无 error overlay。

## 5. 生产验收

部署链路使用 GitHub 已推送提交构建；GCP `/var/www/polydata/release-sha` 用于核对静态版本。后端部署前对远端文件与父提交做 SHA-256 冲突检查，并保留静态与服务文件备份。

2026-07-29 直连生产 smoke 的真实状态：

- Natural hazards API：HTTP 200，约 1.1 秒，906 个 canonical events。
- USGS：OK，445；EONET：OK，350；NWS：OK，111。
- FIRMS：DEGRADED 0，原因是 production configuration required。
- Climate anomaly：DEGRADED 0，原因是 quantitative baseline pipeline 未配置。
- Intel：DEGRADED 1；当前 GDELT 上游有错误，5 条记录未通过地图证据契约。
- Country Risk：PARTIAL 3；Russia、Iran、Ukraine 国家面可交互，1 个复合区域被拒绝。
- Headless 软件渲染环境自动进入 SVG FALLBACK；32 个事件元素可交互，无横向溢出、无前端 error overlay。
- 生产 Inspector 能同时展示 Russia 的 OFAC sanctions evidence 与 UCDP country-risk evidence，且不显示 Related Weather Markets。

测试期间同时保留多组持续刷新整套 dashboard 的无头浏览器会话，叠加 LOB 与 panel batch 请求后，API health probe 连续超时。现有 `polydata-serving-healthcheck` 按 2 次确认、3 次/30 分钟预算和 warmup/backoff 规则执行了有界恢复，因此窗口内出现短暂 502。关闭验收会话后，GCP 本机 `/health` 恢复为 HTTP 200 / 3ms，自然灾害、Intel 和 geo/sanctions 接口恢复。此次没有通过扩大 worker、关闭 watchdog 或修改 systemd 来掩盖测试负载。

## 6. 当前明确的覆盖缺口

- FIRMS 凭据/数据配置未提供，因此不能声称全球卫星火点覆盖完成。
- 定量气候异常 baseline pipeline 未配置，因此不能声称重大气象异常已具备全球定量覆盖。
- GDELT 当前降级，Intel 只展示通过证据门槛的记录，不把弱 proxy 作为热点。
- Headless 验收覆盖了 SVG fallback；真实硬件 GPU 的长时间 FPS/功耗基准不在本次环境中完成。
- 多个完整 dashboard 并发持续刷新会给共享 API 带来明显容量压力；本轮验证了 bounded recovery，但没有把短时 smoke 扩大为正式容量基准。

以上缺口都以 source health、coverage gap 或 rejected count 呈现，不会被包装成完整覆盖或成功状态。
