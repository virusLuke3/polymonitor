import { render, type ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';
import { Panel } from '../../src/components/Panel';
import { PanelDataControls } from '../../src/panels/shared/PanelDataControls';
import { LocaleProvider } from '../../src/services/i18n';
import '../../src/styles/fonts.css';
import '../../src/styles/base-layer.css';
import '../../src/styles/panel-layout-stability.css';
import './preview.css';

// Design artifact only. No collectors, network reads, registry or layout writes.
// All identities, amounts, dates and political events below are fictional fixtures.
type Tone = 'blue' | 'purple' | 'cyan' | 'amber' | 'orange' | 'muted' | 'green';
const tone = (v: Tone) => `pol-${v}`;
function Tabs({ values, value, set }: { values: string[]; value: number; set: (v: number) => void }) {
  return <div className="wm-panel-tabs pol-tabs" aria-label="视图选择">{values.map((x, i) =>
    <button type="button" key={x} aria-pressed={value === i} onClick={() => set(i)}>{x}</button>)}</div>;
}
function Scope({ name, tag, color = 'cyan' }: { name: string; tag: string; color?: Tone }) {
  return <div className="pol-scope"><strong>{name}</strong><span className={`pol-tag ${tone(color)}`}>{tag}</span></div>;
}
function Note({ children, color = 'amber' }: { children: ComponentChildren; color?: Tone }) {
  return <div className={`pol-note ${tone(color)}`}>{children}</div>;
}
function Stat({ label, value, color = 'blue', suffix }: { label: string; value: string; color?: Tone; suffix?: string }) {
  return <div className="pol-stat"><strong className={tone(color)}>{value}<small>{suffix}</small></strong><span>{label}</span></div>;
}
function Bar({ label, value, percent, color = 'blue', sub }: { label: string; value: string; percent: number; color?: Tone; sub?: string }) {
  return <div className="pol-bar"><div><span>{label}</span><b className={tone(color)}>{value}</b></div><div className="pol-track"><i className={tone(color)} style={{ width: `${percent}%` }} /></div>{sub && <small>{sub}</small>}</div>;
}
function Row({ left, right, color = 'muted' }: { left: ComponentChildren; right: ComponentChildren; color?: Tone }) {
  return <div className="pol-row"><span>{left}</span><b className={tone(color)}>{right}</b></div>;
}
function Evidence({ children }: { children: ComponentChildren }) {
  return <details className="pol-evidence"><summary>原始记录与口径</summary><div>{children}</div></details>;
}
function Timeline({ rows }: { rows: { date: string; title: string; detail: string; state: 'done' | 'current' | 'pending' }[] }) {
  return <ol className="pol-timeline">{rows.map(r => <li key={r.title} data-state={r.state}><span>{r.date}</span><div><b>{r.title}</b><p>{r.detail}</p></div><i aria-label={r.state === 'done' ? '有记录' : r.state === 'current' ? '进行中' : '待发生'} /></li>)}</ol>;
}
function Trend({ series, labels, axis = ['T−14', 'T−7', 'T−1'] }: { series: { name: string; color: Tone; values: number[] }[]; labels: [number, number]; axis?: string[] }) {
  const [min, max] = labels;
  const y = (v: number) => 70 - (v - min) / (max - min) * 54;
  return <div className="pol-trend"><svg viewBox="0 0 280 90" role="img" aria-label={`样例趋势：${series.map(s => s.name).join('、')}`}>
    {[min, (min + max) / 2, max].map(v => <g key={v}><line x1="24" x2="276" y1={y(v)} y2={y(v)} /><text x="0" y={y(v) + 3}>{v}</text></g>)}
    {series.map(s => <polyline key={s.name} className={tone(s.color)} points={s.values.map((v, i) => `${25 + i * 249 / (s.values.length - 1)},${y(v)}`).join(' ')} />)}
    {axis.map((a, i) => <text key={a} x={24 + 125 * i} y="86" text-anchor={i === 2 ? 'end' : 'start'}>{a}</text>)}
  </svg><div className="pol-legend">{series.map(s => <span className={tone(s.color)} key={s.name}>━ {s.name}</span>)}</div></div>;
}
function MarketLink({ children = '关联 Market · 查看结算条件' }: { children?: ComponentChildren }) {
  return <details className="pol-market"><summary>{children} <span>↗</span></summary><div>设计样例 MARKET-DEMO。正式接入后使用已有 Market 选择能力，显示结算事件、指定来源、截止时间与映射版本；不以民调支持率冒充胜选概率。</div></details>;
}

function Election() {
  const [phase, set] = useState(0);
  return <><Scope name="示例州 · 州长选举" tag={['投票前', '计票中', '结果核验'][phase]} />
    <Tabs values={['民调', '计票', '认证']} value={phase} set={set} />
    {phase === 0 ? <><div className="pol-stats"><Stat label="候选人 A · 支持率" value="48.2" suffix="%" /><Stat label="候选人 B · 支持率" value="46.1" suffix="%" color="purple" /><Stat label="明确未决定" value="5.7" suffix="%" color="muted" /></div>
      <Trend series={[{ name: '候选人 A', color: 'blue', values: [46.1, 46.6, 47, 46.8, 47.7, 48.2] }, { name: '候选人 B', color: 'purple', values: [47.2, 47, 46.5, 46.8, 46.3, 46.1] }]} labels={[44, 50]} />
      <Row left="最新单次民调 · 样例机构" right="n = 1,200" /><div className="pol-small">Likely voters · 在线调查 · T−3 至 T−1</div>
      <Evidence>样例的三个比例来自同一道题。原始行应保留题目、调查区间、公开时间、方法与候选人身份。趋势为样例调查序列；不把抽样误差当成胜选区间。历史误差模型尚未实现。</Evidence></>
      : phase === 1 ? <><div className="pol-stats"><Stat label="A 当前票数" value="102,340" /><Stat label="B 当前票数" value="98,210" color="purple" /></div><Bar label="候选人 A" value="51.03%" percent={51.03} /><Bar label="候选人 B" value="48.97%" percent={48.97} color="purple" /><Note>尚有未计票 · 当前领先不等于获胜</Note><Row left="北县 · 待计邮寄票" right="约 12,000" color="amber" /><Row left="南县 · 待计票数量" right="来源未提供" /><Evidence>已计票共 200,550。剩余票只能使用来源发布的估计及范围，不能由 precincts reporting 比例倒推。更正票数保留版本；媒体 call 与认证分开。</Evidence></>
      : <><Note color="purple">媒体已宣布结果 · 官方认证尚未完成</Note><Timeline rows={[{ date: 'D+1', title: '媒体宣布 A 获胜', detail: '媒体判断记录；不等于认证', state: 'done' }, { date: 'D+3', title: '地方复核进行中', detail: '一处计票更正，保留前后版本', state: 'current' }, { date: 'D+14', title: '认证期限', detail: '是否满足 Market，取决于其 Rules', state: 'pending' }]} /><Evidence>认证、重新计票和司法事件可并行存在。合约如果指定媒体宣布，不擅自改为等待认证；如果指定官方结果，不把媒体判断当成终局证据。</Evidence></>}
    <MarketLink /></>;
}
function EarlyVote() {
  const [tab, set] = useState(0);
  return <><Scope name="示例州 · 提前投票" tag="T−2 日" color="cyan" /><Tabs values={['进度', '地区']} value={tab} set={set} />
    <div className="pol-hero pol-cyan"><span>已收到邮寄选票</span><strong>684,200<small> 份</small></strong><span>较前一报告 +24,300 · 同口径日增量</span></div>
    {tab === 0 ? <><div className="pol-vote-strip"><span>申请 <b>920K</b></span><i>→</i><span>寄出 <b>900K</b></span><i>→</i><span className="pol-cyan">退回 <b>684.2K</b></span></div><Bar label="退回 / 寄出" value="76.0%" percent={76.02} color="cyan" /><Trend series={[{ name: '本届累计 · 万份', color: 'cyan', values: [10, 17, 25, 34, 52, 68.42] }, { name: '上届同距选举日', color: 'muted', values: [8, 14, 22, 31, 45, 60] }]} labels={[0, 80]} axis={['T−12', 'T−7', 'T−2']} /></>
      : <><Row left="北县 · 退回 / 寄出" right="182K / 250K" color="cyan" /><Row left="南县 · 退回 / 寄出" right="230K / 300K" color="cyan" /><Row left="其他地区" right="272.2K / 350K" color="cyan" /><Note>登记党派不代表选票投给谁</Note></>}
    <Evidence>现场提前投票与邮寄票分列；被拒、待补正选票单列。上届对照按距投票日对齐，分母及地区覆盖一致才比较。人口统计字段仅在来源提供且允许使用时显示。</Evidence><MarketLink /></>;
}
function Nomination() {
  const [tab, set] = useState(0);
  return <><Scope name="示例党 · 提名竞逐" tag="代表票" color="purple" /><Tabs values={['提名路径', '初选日历']} value={tab} set={set} />
    {tab === 0 ? <><div className="pol-delegate"><Stat value="860" label="A 已分配代表票" color="purple" /><div><b className="pol-amber">还差 141</b><span>门槛 1,001 / 总数 2,000</span></div></div><div className="pol-threshold"><div><i className="pol-purple" style={{ width: '43%' }} /><i className="pol-blue" style={{ width: '31%' }} /><i className="pol-muted" style={{ width: '26%' }} /></div><b style={{ left: '50.05%' }} /><span>提名门槛</span></div><div className="pol-legend"><span className="pol-purple">A 860</span><span className="pol-blue">B 620</span><span>未分配 520</span></div><Note color="purple">下一个初选：示例州乙 · 80 票</Note><Row left="分配规则" right="比例分配 · 门槛 15%" /><Row left="候选人 B" right="仍在参选" color="blue" /></>
      : <><Timeline rows={[{ date: 'T+3', title: '示例州乙 · 80 代表票', detail: '比例分配，达到 15% 门槛', state: 'current' }, { date: 'T+10', title: '示例州丙 · 60 代表票', detail: '按党规核实，不套统一规则', state: 'pending' }, { date: 'T+35', title: '党代会', detail: '实际正式提名另记事件', state: 'pending' }]} /></>}
    <Evidence>这是虚构的党规与代表票配置。pledged、unpledged、allocated、bound 等来源语义单独保留；退选不自动清零代表票。背书、备案、取得提名不能互相替代。</Evidence><MarketLink /></>;
}
function Seats() {
  const [chamber, setChamber] = useState(0), [selected, setSelected] = useState<number | null>(null);
  const counts = chamber === 0 ? [48, 46, 6] : [41, 53, 6];
  return <><Scope name="示例议会 · 100 席" tag="多数 51" color="amber" /><Tabs values={['本届计票', '上届对照']} value={chamber} set={setChamber} />
    <div className="pol-stats"><Stat label="A 党已判定" value={String(counts[0])} /><Stat label="B 党已判定" value={String(counts[1])} color="purple" /><Stat label="待定" value={String(counts[2])} color="amber" /></div>
    <div className="pol-seat-grid" aria-label="100 席示意，每格一席">{Array.from({ length: 100 }, (_, i) => <button key={i} type="button" className={tone(i < counts[0] ? 'blue' : i < counts[0] + counts[1] ? 'purple' : 'amber')} aria-label={`查看样例席位 ${i + 1}`} onClick={() => setSelected(i + 1)} />)}</div>
    <label className="pol-seat-picker">选取席位 <select value={selected ?? ''} onChange={e => setSelected(Number(e.currentTarget.value) || null)}><option value="">选择一个席位</option>{Array.from({ length: 100 }, (_, i) => <option key={i} value={i + 1}>示例席位 {i + 1} · {i < counts[0] ? 'A 党' : i < counts[0] + counts[1] ? 'B 党' : '待定'}</option>)}</select></label>
    <div className="pol-small">每格一席 · 排列不表示地理位置</div><Note color="blue">{selected ? `已选示例席位 ${selected} · ${selected <= counts[0] ? 'A 党已判定' : selected <= counts[0] + counts[1] ? 'B 党已判定' : '待定'}` : `A 党距多数还差 ${51 - counts[0]} 席`}</Note>
    <Row left="待定选区 01" right="差距 0.4pp" color="amber" /><Row left="待定选区 02" right="重新计票" color="amber" />
    <Evidence>正式数据按选区与边界版本存储。媒体判定、官方认证、实际就任各有口径；席位汇总只统计同一口径。不同边界的历史对照须映射后才显示。席位概率分布是后续独立模型。</Evidence><MarketLink /></>;
}
function Finance() {
  const [tab, set] = useState(0);
  return <><Scope name="示例州 · 候选人资金" tag="申报期 Q3" color="orange" /><Tabs values={['候选人', '独立支出']} value={tab} set={set} />
    {tab === 0 ? <><div className="pol-finance-head"><Stat label="A 筹款 · 本报告期" value="$12.4" suffix="M" color="orange" /><Stat label="B 筹款 · 本报告期" value="$10.2" suffix="M" color="purple" /></div><div className="pol-legend"><span className="pol-orange">■ 筹款</span><span className="pol-cyan">■ 支出</span><span>单位：USD M</span></div><div className="pol-finance-bars">{[['A', 12.4, 9.1], ['B', 10.2, 9.6]].map(([name, a, b]) => <div key={String(name)}><b>{name}</b><div><i className="pol-orange" style={{ width: `${Number(a) / 14 * 100}%` }}>{a}</i><i className="pol-cyan" style={{ width: `${Number(b) / 14 * 100}%` }}>{b}</i></div></div>)}</div><Row left="A 期末现金 / 债务" right="$4.1M / $0.3M" color="orange" /><div className="pol-small">样例申报 · 已修订 1 次 · 资金不等于选票</div></>
      : <><div className="pol-stats"><Stat label="支持 A 的独立支出" value="$3.2M" color="orange" /><Stat label="反对 A 的独立支出" value="$2.1M" color="purple" /></div><Bar label="委员会 X · 支持 A" value="$1.8M" percent={56.25} color="orange" /><Bar label="委员会 Y · 反对 A" value="$2.1M" percent={65.6} color="purple" /><Note>独立支出单列，不并入候选人筹款</Note></>}
    <Evidence>FEC candidate / committee / filing ID 去重；报告期与申报日分开。修订替换有效版本，保留原件。独立支出不等于所有广告投放量、曝光或覆盖人群；后者需独立来源。</Evidence><MarketLink /></>;
}
function Government() {
  const [tab, set] = useState(0);
  return <><Scope name="示例国 · 组阁进程" tag="议会制" color="purple" /><Tabs values={['联盟', '程序']} value={tab} set={set} />
    {tab === 0 ? <><div className="pol-hero pol-purple"><span>A + C 联盟 · 已签署协议</span><strong>154<small> / 300 席</small></strong><span>多数门槛 151 · 多出 3 席</span></div><div className="pol-coalition"><div className="pol-blue" style={{ flex: 118 }}>A 118</div><div className="pol-cyan" style={{ flex: 36 }}>C 36</div><div className="pol-unfilled" style={{ flex: 146 }}>其他 146</div></div><Note color="purple">联盟协议已签 · 信任投票待举行</Note><Row left="下一节点" right="T+2 · 信任投票" color="purple" /><Row left="正式就职" right="尚无记录" /></>
      : <Timeline rows={[{ date: 'D+1', title: '席位确认', detail: '按本届正式席位口径', state: 'done' }, { date: 'D+5', title: '联盟协议签署', detail: '需可追溯正式声明', state: 'done' }, { date: 'D+7', title: '信任投票', detail: '议程已列入，尚未投票', state: 'current' }, { date: '待定', title: '任命 / 就职', detail: '依该国规则判定', state: 'pending' }]} />}
    <Evidence>这里只演示议会制。美国两院控制权采用各自党团、议长及平票规则，不能套组阁流程。支持协议、谈判传闻、正式联盟分开；党派席位不等于实际支持票。</Evidence><MarketLink /></>;
}
const billRows = [
  { date: 'D−8', title: '委员会审议通过', detail: '修订版 v2 · 有正式记录', state: 'done' as const },
  { date: 'D−3', title: '众议院通过', detail: '231–198 · v2 文本', state: 'done' as const },
  { date: 'D+1', title: '参议院议程', detail: '尚未最终表决 · 程序性动议另列', state: 'current' as const },
  { date: '待定', title: '两院同文 → 总统处理', detail: '是否签署，必须有新的证据', state: 'pending' as const },
];
function Legislation() {
  const [tab, set] = useState(0);
  return <><Scope name={tab === 0 ? '示例法案 · H.R. DEMO' : '联邦监管文件'} tag={tab === 0 ? '国会立法' : '行政规则'} color="cyan" /><Tabs values={['法案', '监管公告']} value={tab} set={set} />
    {tab === 0 ? <><Note color="cyan"><strong>已过众议院</strong><span>下一步：参议院审议</span></Note><div className="pol-procedure"><span className="done">提出</span><span className="done">委员会</span><span className="done">众院</span><span className="current">参院</span><span>签署</span></div><Timeline rows={billRows} /><Evidence>两院流程可能并行、退回、换版本或否决，不用“完成 60%”解释通过概率。共同提案人不等于承诺赞成票；逐名投票、修正案与同文核对可展开。</Evidence></>
      : <><Note color="cyan">保留现有 Federal Register 公告视图</Note><Timeline rows={[{ date: 'D−6', title: '拟议规则 · 意见征集', detail: '不是国会法案', state: 'done' }, { date: 'D+8', title: '公众意见截止', detail: '使用来源提供的日期', state: 'current' }, { date: '待定', title: '最终规则', detail: '不能推测一定发布或生效', state: 'pending' }]} /><Evidence>沿用 document_number、公布日、effective_on、comments_close_on 与正式 PDF 链接；补齐分页和目标文件跟踪。法规与法案不混用状态。</Evidence></>}
    <MarketLink /></>;
}
function Executive() {
  const [tab, set] = useState(0);
  return <><Scope name="示例行政命令" tag="EO-DEMO" color="orange" /><Tabs values={['时间线', '效力变化']} value={tab} set={set} />
    <div className="pol-document-title"><span className="pol-orange">EXECUTIVE ORDER</span><strong>关键物资采购安排</strong><div className="pol-small">示例文件 · 签署、公示与生效分开</div></div>
    {tab === 0 ? <><div className="pol-doc-dates"><div><span>签署</span><b>D−2</b></div><div><span>公布</span><b>D−1</b></div><div className="pol-orange"><span>生效</span><b>D+7</b></div></div><Note color="orange">已签署并公布 · 尚未到生效日期</Note><Row left="签署证据" right="政府原文" color="orange" /><Row left="公布证据" right="Federal Register / PDF" color="cyan" /></>
      : <><Timeline rows={[{ date: 'D−2', title: '签署版本', detail: '保留正文与条款', state: 'done' }, { date: 'D+7', title: '计划生效', detail: '不同条款可有不同日期', state: 'current' }, { date: '—', title: '修订 / 撤销 / 暂缓执行', detail: '无后续记录，不推测状态', state: 'pending' }]} /></>}
    <Evidence>行政命令、总统公告、备忘录与紧急状态通知分型。法院命令要记录适用条款、地区与效力时间，不能将新闻标题推导为整份命令无效。</Evidence><MarketLink /></>;
}
function Appointments() {
  const [tab, set] = useState(0);
  return <><Scope name="示例人选 A · 部长职位" tag="PN-DEMO" color="purple" /><Tabs values={['确认程序', '表决记录']} value={tab} set={set} />
    {tab === 0 ? <><div className="pol-person"><span className="pol-avatar pol-purple" aria-hidden="true">A</span><div><b>示例人选 A</b><p>委员会已报告 · 等待全院审议</p></div></div><div className="pol-stats"><Stat label="委员会赞成" value="14" color="cyan" /><Stat label="委员会反对" value="8" color="purple" /><Stat label="最终确认票" value="—" color="muted" /></div><Timeline rows={[{ date: 'D−9', title: '正式提名提交', detail: '关联职位与提名批次', state: 'done' }, { date: 'D−3', title: '委员会表决 14–8', detail: '不是参议院最终确认', state: 'done' }, { date: 'D+2', title: '全院程序性投票', detail: '最终确认日期尚未安排', state: 'current' }]} /></>
      : <><Note color="purple">程序性表决与最终确认分列</Note><Row left="委员会表决" right="14–8 · 已记录" color="cyan" /><Row left="全院结束辩论" right="待投票" color="amber" /><Row left="全院最终确认" right="未发生" /><Row left="正式就职" right="未发生" /><Evidence>正式接入后逐名展示赞成、反对、未投票；公开表态附原文，不计为实际票数。</Evidence></>}
    <MarketLink /></>;
}
const appropriations = ['农业', '商贸司法', '国防', '能源水利', '金融服务', '国土安全', '内政环境', '劳工教育', '立法部门', '军建退伍军人', '国务院外交', '交通住房'];
function Funding() {
  const [tab, set] = useState(0), [selected, setSelected] = useState('国土安全');
  return <><Scope name="示例财政年度 · 联邦拨款" tag="CR 到期" color="amber" /><Tabs values={['资金覆盖', '立法窗口']} value={tab} set={set} />
    <div className="pol-deadline"><span>距当前 CR 到期</span><strong>02<small>天</small> 14<small>时</small></strong><span>设计时点冻结 · 截止 23:59 ET</span></div>
    {tab === 0 ? <><div className="pol-appropriations">{appropriations.map((x, i) => <button type="button" key={x} onClick={() => setSelected(x)} className={tone(i < 4 ? 'cyan' : 'amber')} aria-pressed={selected === x}>{x}<small>{i < 4 ? '年度拨款' : '临时 CR'}</small></button>)}</div><div className="pol-legend"><span className="pol-cyan">4 项全年覆盖</span><span className="pol-amber">8 项临时覆盖</span></div><Note color={appropriations.indexOf(selected) < 4 ? 'cyan' : 'amber'}>{selected} · {appropriations.indexOf(selected) < 4 ? '本财政年度已获拨款' : '当前 CR 到期后需续拨'}</Note></>
      : <><Timeline rows={[{ date: 'T−48h', title: '众院表决窗口', detail: '议程中的表决，不代表通过', state: 'current' }, { date: '待定', title: '参院同文通过', detail: '必须核实程序与文本', state: 'pending' }, { date: 'T=0', title: '资金到期', detail: '签署与拨款效力分别核验', state: 'pending' }]} /><Note>OMB 预案不等于已发生停摆</Note></>}
    <Evidence>12 类为常规拨款分类，不等于 12 个部门。部门与项目覆盖以法案正文为准；部分资金缺口、实际停摆通知、Market 定义分别判断。财政年度和准确时区进入身份。</Evidence><MarketLink /></>;
}

const designs = [
  { id: 'election', title: 'ELECTION WATCH', name: '选举观察', view: Election, ref: 'AAII 的分类大数字 + Market Breadth 多序列图', source: 'Decision Labs / 民调机构原文 / 官方计票；AP 按授权接入', description: '民调、计票、认证按事件阶段切换主视图；所有阶段可回看。' },
  { id: 'early-vote', title: 'EARLY VOTE', name: '提前投票', view: EarlyVote, ref: 'Market Breadth 趋势 + AAII 比例条', source: '州选举机关 / AP advance turnout；EAC 仅历史校准', description: '申请、寄出、退回与现场投票；同距选举日对照。' },
  { id: 'nomination', title: 'NOMINATION PATH', name: '提名路径', view: Nomination, ref: 'AAII 门槛条 + Earnings Calendar 日期分组', source: '政党规则 / 州初选机关 / AP delegate reports', description: '代表票与规则门槛为主，民调、退选与背书为辅助。' },
  { id: 'seats', title: 'SEAT BALANCE', name: '议席格局', view: Seats, ref: 'Sector Heatmap 分类格 + AAII 大数值', source: '官方选区 / 计票 / 认证 / 议会成员表', description: '每格一席，区分已判定、待定、认证和实际就任。' },
  { id: 'finance', title: 'CAMPAIGN FINANCE', name: '竞选资金', view: Finance, ref: 'Macro Indicators 主数值 + 配对条形图', source: 'OpenFEC；广告素材与曝光需另有来源', description: '筹款、支出、现金、债务与独立支出；报告期和修订可追溯。' },
  { id: 'government', title: 'GOVERNMENT FORMATION', name: '控制权与组阁', view: Government, ref: 'Strategic Posture 分类强调块 + 席位分布', source: '各国议会 / 政党正式声明 / 政府公报', description: '席位、联盟协议、信任投票、任命与就职分别陈述。' },
  { id: 'legislation', title: 'POLICY PROGRESS', name: '立法与监管进程', view: Legislation, ref: '现有 Policy Progress + Earnings Calendar 时间节点', source: 'Congress.gov / 两院投票；复用 Federal Register', description: '升级现有面板，保留监管公告，增加法案分支。' },
  { id: 'executive', title: 'EXECUTIVE ACTIONS', name: '行政命令', view: Executive, ref: 'Strategic Posture 侧边色条 + 日期块', source: '政府签署文件 / Federal Register / GovInfo', description: '签署、公布、生效与效力变更，不把所有总统文件当行政命令。' },
  { id: 'appointments', title: 'APPOINTMENTS', name: '政治任命', view: Appointments, ref: 'Tech Events 人物/日期层级 + AAII 票数对比', source: 'Congress nominations / 参议院 / 委员会 / 政府', description: '提名、听证、委员会、程序票、最终确认与就职。' },
  { id: 'funding', title: 'FUNDING DEADLINE', name: '拨款与停摆', view: Funding, ref: 'Fear & Greed 主数字层级 + Heatmap 状态矩阵', source: '拨款法案 / 两院议程 / 总统签署 / OMB及机构通知', description: '倒计时与 12 类拨款覆盖，资金缺口和实际停摆分开。' },
];
type Scenario = 'normal' | 'failed' | 'unsupported';
function DesignPanel({ design, scenario }: { design: typeof designs[number]; scenario: Scenario }) {
  const [revision, setRevision] = useState(0);
  const View = design.view;
  return <div className="wm-panel-slot" data-design-id={design.id}>
    <Panel title={design.title} dataPanelId={`design-politics-${design.id}`} className="pol-panel" controls={<PanelDataControls onRefresh={() => setRevision(v => v + 1)}>
      <strong>{design.name} · 设计原型</strong><p>所有数据是虚构设计样例，未接生产 API。刷新只重置样例交互。</p><p>{design.description}</p><p>拟接来源：{design.source}</p><p>视觉借鉴：{design.ref}。参考为仓库保存的 2026-11-05 WorldMonitor 实图。</p><p>样例重置次数：{revision}</p>
    </PanelDataControls>}>
      <div className="pol-body">{scenario === 'unsupported' ? <div className="pol-empty"><strong>这个范围尚未接入</strong><p>{design.name}需要相应国家、选区或程序的数据源。</p><p>不换成其他地区，不填零或绘制空图。</p></div> : <>{scenario === 'failed' && <Note>样例：来源更新中断 · 下方保留上一版记录</Note>}<View key={revision} /></>}
        <div className="pol-fixture">设计样例 · {design.name} · 非当前政治数据</div>
      </div>
    </Panel>
  </div>;
}
function App() {
  const [expanded, setExpanded] = useState(false), [scenario, setScenario] = useState<Scenario>('normal');
  return <LocaleProvider><div className="wm-shell pol-preview">
    <div className="pol-toolbar"><div><b>POLYMONITOR <span>POLITICS / 设计预览</span></b><p>8 类 Market · 10 个面板 · 9 个新增 + 1 个升级</p></div><div className="pol-preview-controls"><label><input type="checkbox" checked={expanded} onChange={e => setExpanded(e.currentTarget.checked)} />展开设计内容</label><label>示例状态 <select value={scenario} onChange={e => setScenario(e.currentTarget.value as Scenario)}><option value="normal">正常数据</option><option value="failed">刷新失败保留</option><option value="unsupported">范围尚未接入</option></select></label></div></div>
    <div className="pol-disclaimer">全部为虚构设计样例。默认导入现有五列与原始高度；“展开”只方便查看本设计，不修改网站布局。</div>
    <main className={`wm-dashboard ${expanded ? 'pol-expanded' : ''}`}><div className="wm-panels-grid" id="politics-grid">{designs.map(d => <DesignPanel key={d.id} design={d} scenario={scenario} />)}</div></main>
    <details className="pol-design-index"><summary>每个面板的来源、参考与边界</summary>{designs.map(d => <p key={d.id}><b>{d.name}</b>：{d.description}<br />{d.source}<br /><span>{d.ref}</span></p>)}</details>
  </div></LocaleProvider>;
}
render(<App />, document.getElementById('app')!);
