# 网站数据传输契约

网站静态文件和 Nginx 在公网主机，本机现有 API 读取正式 SQLite、Redis 和既有数据拥有者。浏览器通过同域 `/wm-api/` 访问；反向连接仅提供传输，不新增采集器、数据副本或成功时间。主机、密钥、跳板、端口和转发列表属于私有 `.env`，本文和脚本不保存个人地址。

## 连接与资源预算

- `scripts/runtime/website_link.py` 读取 `POLYMONITOR_WEB_LINK_TARGET`、跳板名称、现有专用 SSH 身份及转发列表。可选 `POLYMONITOR_WEB_LINK_PROFILES_JSON` 为 `bulk`、`interactive` 等独立连接声明 `remote`/`local` 转发列表。每个方向最多八项，仅允许回环地址；配置缺失或无效则停止启动。
- 默认连接保留现有消费者。额外 `polymonitor-website-link@bulk.service` 为公共批量响应提供第二条连接；`@interactive` 专门承载市场目录、详情、图表、成交、Oracle、bootstrap 和 health。大新闻/地图响应的 TCP 丢包不再阻塞市场连接。Nginx 的 bulk pool 有两个目标，interactive pool 有一个目标；部署时核对空闲端口，禁止抢占其他服务。
- 每个 profile 可单独声明 `target`、`jump_node`；未声明则继承公共配置，空 `jump_node` 明确不使用跳板。这样可将现有 bulk 连接切到已验证的私有网络路径，同时保留另一条不同路径的 bulk 连接与 interactive，不新增采集器或修改采集代理。目标仍使用原网站 HostKeyAlias 校验；未知键、跳板、非法目标或非回环转发拒绝启动。
- profile 也可声明 `http_proxy`，通过现有独立本机 HTTP CONNECT 代理建立网站 SSH；必须同时声明空 `jump_node`。只接受明确端口的回环 HTTP 地址，不接受认证、路径、查询参数或远程代理地址；依赖 `/usr/bin/nc` 的 CONNECT 支持。SSH 身份、目标 HostKeyAlias、回环转发和保活不变，不修改代理选择或采集路由。代理不可达时该连接失败并由原 systemd 策略恢复，不能静默改为其他出口。
- 每条 SSH 连接开启压缩，连接超时 15 秒，保活 10 秒、连续三次无回应退出；转发失败退出，systemd 五秒后重连。SSH 存活不证明 HTTP 能正常通过，必须检查实际业务响应。跳板使用独立网站 SSH 进程，不复用或重启采集器连接，不修改主 Clash 选择、LOB 密钥和端口。
- 网站主机同时配置服务端保活：`deploy/ssh/50-polymonitor-link-keepalive.conf` 对部署用户设置 15 秒探测、三次未响应释放连接，避免客户端失联后旧反向端口长期占用。先 `sshd -t` 再 reload，分开重连 bulk/interactive 并验证 HTTP；不重启 SSH 主服务或其他采集连接。该配置不会消除网络延迟，也不保证每次丢包都在精确 45 秒内恢复。
- 跳板授权仅给网站已有专用身份增加目标 SSH 端口的 `permitopen`；不得放开全地址转发。最终生产配置与测试过但未使用的出口分开记录。
- Gunicorn `gthread` 的默认首数据等待及 keepalive 组合会提前关闭高延迟转发连接。`POLYDATA_GUNICORN_KEEPALIVE_SECONDS=30`；Nginx pool 的 idle keepalive 为 15 秒、每连接最多 100 请求，bulk/interactive 每个 worker 分别最多保留 8/4 条空闲连接。使用 HTTP/1.1 并清空 upstream `Connection` 头，才会真正复用。
- Nginx pool 地址由 `POLYMONITOR_WEB_API_UPSTREAMS_JSON` 和 `POLYMONITOR_WEB_INTERACTIVE_UPSTREAM` 渲染进 `deploy/nginx/polydata-relay-upstreams.conf.example`。站点的普通 API 指向 bulk pool，市场路由及 bootstrap/health 指向 interactive pool。现有 LOB 专用路由、限流和实时性保持各自契约。配置校验失败立即恢复原配置，成功后 reload。
- 用 `scripts/deploy/render_panel_transport.py` 从 Runtime API registry 渲染 `deploy/nginx/polymonitor-panel-transport.conf`，再包含于网站 server；只有精确注册路径参与，地图查询和流式路由不匹配。公共快照连接 2 秒、连续无数据等待 8 秒，错误/超时/502/503/504 最多切换一次，总切换窗口 18 秒。只有尚未向客户端发送响应时才能切换；这不是整个下载的绝对截止时间，也不保证消除全部公网波动。天气 books 精确路由复用 interactive，连接 2 秒、等待 6 秒，保持 `no-store`/原报价有效期。LOB、视频流、自然灾害已有精确缓存路由和限流保持原契约；不会对上游 403/429 重试，也不启用非幂等请求重放。
- 同一 renderer 的 `--upstreams-output` 从私有配置生成 pool：bulk 的 `max_fails=0` 关闭整条连接的被动摘除，避免两个慢来源把所有 peer 同时摘除后产生 `no live upstreams`。每次失败请求仍按前项预算切到另一条连接，SSH 断线仍由 systemd 重连；这不把失败响应变成成功或长期旧缓存。只接受回环 socket、bulk 最多四条，实际部署保持既有两条。`POLYMONITOR_WEB_PANEL_UPSTREAM` 指向独立 `@panels` 连接，精确注册快照及 `/content/latest` 复用该连接，失败才回退最后一条 bulk 连接；地图大包继续使用原 bulk pool。Panel pool 最多保留四条空闲连接，15 秒回收、每条最多 100 请求。此隔离降低地图流量的 TCP 队头阻塞，不代表网络带宽已增加。
- bulk 地址顺序具有含义：第一条为已验证的主路径，其余为 Nginx `backup`，不再用 `least_conn` 将正常请求分配给已知高丢包路径。最后一条同时作为 Panel pool 的备用。部署必须分别验证主路径业务读取和备用可达性；有备用并不保证两个路径独立失效。旧默认隧道及其其他消费者保持运行。

## 数据与时钟

前端 `/runtime/`、`/v1/runtime/` 批量读取与 `/content/` 正文列表共同遵守共享下载并发预算（桌面三条、手机两条）。市场目录保持队列优先级；后台大正文不能绕过队列或依靠重复失败抢占带宽。

传输隔离不改变采集周期、正式落库、快照生成时间、浏览器检查周期或最大旧值保留期。市场目录继续由共享 Runtime 每五分钟检查，最多保留十五分钟；断网显示原快照和原时钟。自然灾害同源 Nginx 缓存遵守已有 30/60 秒有效期，不无限提供过期内容；市场接口继续 `no-store`，不把实时报价转换为网关旧缓存。

共享 API HTTP 层在回连之前压缩 Runtime Panel registry 中的公共只读快照、三个公共市场分析 lens 和 `/content/latest`。接受 gzip 的 GET/200 JSON 且正文至少 1 KiB 才参与；流、已有编码、Set-Cookie、错误和其他路由保持原样。压缩保留原数据、源时间、Cache-Control 和 Vary，不增加缓存寿命；不能只在腾讯云出站时压缩，否则中间回连仍传输大正文。注册表复用避免每次新增公共 Panel 再补一套传输逻辑。

地图公共 JSON（hazards map/related-markets、world signals/infrastructure、transport map/aviation-viewport、weather map-query）也在后端压缩，避免其大响应占用同一浏览器下载队列。它们仅复用压缩规则，不加入前述只读快照的短等待切换；按需查询仍遵守自身源预算。瓦片、流媒体、LOB、错误响应不参与此转换。

部署环境已具备可选 Brotli 时，按客户端 `Accept-Encoding` 的权重选择 br（quality 4）或 gzip（level 5）；缺少该库时保持 gzip 回退，不让 API 启动失败，也不向不接受该编码的客户端发送压缩正文。原文小于 1 KiB 或压缩后没有缩小时不转换。浏览器还原后字段完全一致；这只减少传输，不把源缺失或旧快照改成实时数据。

AI Insights、Special Radar、Trend Watch 复用 `agent:market-wide:snapshot / v1:<lens>`。模型与 seed 的运行身份和预算见 [Agent 索引](../agent/README.md)。生成成功、输入覆盖和展示成功分别验证，缺失输入仍保留原限制。

## 发布验收

1. 核对实际进程环境、SSH socket、监听归属及对应配置；不只检查 unit active。模拟建立连接后九秒才发送 HTTP，确认后端没有提前关闭。
2. 同时请求市场目录、详情、图表和较大批量响应；对比本机、远端回环、公网的状态、耗时、记录数和原始时间。空列表需要来源证据，历史日汇总不能当实时流。
3. 从普通公网首页使用真实 API/瓦片加载，保留已有布局；桌面、手机分别截图。验证缓存刷新、离线保留及离线重载、联网自动取得下一份有效响应。不能用手动注入 online 事件或替换响应代替线上验收。
4. 新代码仅发布本任务提交；源码、部署版本、数据结果和长时间稳定性分别记录。已有源缺失、业务语义限制与本次传输修复分开报告。

## LOB 读取的传输隔离

已有 market-data HTTP book reader 的本机端口、程序、源数据、资格与时间语义不变。反向部署可在现有 interactive profile 中增加单独回环转发，并配置 `POLYMONITOR_WEB_LOB_UPSTREAM`。renderer 生成 `polymonitor_book_api` 后，只把站点现有 token book location 的 upstream 改为该 pool；保留该 location 的限流、连接 1 秒、读取 3 秒和无 HTTP 缓存。旧转发保留给现有消费者，不改 LOB 密钥，也不重启采集器。响应送达与源 `upstreamCompleteness`、事件时间、连续性资格分别验收；HTTP 200 不能把 UNKNOWN 改成完整。
