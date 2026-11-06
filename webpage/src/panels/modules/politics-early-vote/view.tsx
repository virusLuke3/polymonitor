import { useState } from 'preact/hooks';
import { Bar, Empty, Evidence, Row, Scope, Shell, Tabs, useCopy } from '../../shared/politics/ui';
import { num } from '../../shared/politics/model';
import type { Payload } from './model';
export function View({ data }: { data?: Payload }) {
  const t=useCopy(), [tab,set]=useState('progress'), total=data?.totals, counties=data?.items || [];
  return <Shell id="politics-early-vote" title={t('提前投票','EARLY VOTE')} data={data} explanation={t('北卡州邮寄票报告，逐县聚合。已接受、收到但未计、未完成及作废分开；登记党派不代表投票选择。','North Carolina mail-ballot report aggregated by county. Accepted, received-not-counted, outstanding and spoiled ballots remain separate.')}>
    <Scope name="US · NORTH CAROLINA" tag={data?.electionDate}/><Tabs values={[[ 'progress',t('邮寄票','Mail ballots') ],['counties',t('地区','Counties')]]} value={tab} set={set}/>
    {total ? <><div className="pol-hero pol-cyan"><span>{t('已接受的邮寄选票','Accepted mail ballots')}</span><strong>{num(total.accepted)}</strong><span>{counties.length} / {data?.expectedCounties} {t('县','counties')}</span></div>
      {tab==='progress' ? <><div className="pol-vote-strip"><span>{t('寄出','Sent')}<b>{num(total.sent)}</b></span><i>→</i><span className="pol-cyan">{t('接受','Accepted')}<b>{num(total.accepted)}</b></span><span>{t('收到未计','Received, not counted')}<b>{num(total.receivedNotCounted)}</b></span></div><Bar label={t('接受 / 寄出','Accepted / sent')} value={total.sent ? `${num(total.accepted/total.sent*100,1)}%`:'—'} percent={total.sent ? total.accepted/total.sent*100:null} tone="cyan"/><Row label={t('尚未完成','Outstanding')} value={num(total.outstanding)}/><Row label={t('因现场提前投票作废','Spoiled for early in-person vote')} value={num(total.spoiled)}/></> : counties.slice().sort((a,b)=>b.sent-a.sent).map(c=><Row key={c.id} label={c.id} value={`${num(c.accepted)} / ${num(c.sent)}`} tone="cyan"/>)}
      <Evidence><p>{t('“接受”不是全部退回；收到但未计单列。原文件的日期是选举日期，不能用作报告发布时间。当前仅覆盖北卡邮寄票，上届同距选举日对照和现场提前票尚未接入。','Accepted is not all returned ballots. The file date identifies the election, not report publication. Coverage is North Carolina mail ballots; comparable historical series and in-person early voting are unavailable.')}</p></Evidence>
    </> : <Empty>{t('尚未取得该州邮寄票统计。','Mail-ballot statistics are not yet available.')}</Empty>}
  </Shell>;
}
