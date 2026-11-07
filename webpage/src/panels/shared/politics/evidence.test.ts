import { expect, it } from 'vitest';
import { valid as election } from '../../modules/politics-election/model';
import { valid as nomination } from '../../modules/politics-nomination/model';
import { valid as finance } from '../../modules/politics-campaign-finance/model';
import { valid as appointments } from '../../modules/politics-appointments/model';

const base = { panelId:'test', schemaVersion:1, generatedAt:'2026-11-07T08:00:00Z', sources:[] };

it('keeps congressional primary N/A separate from historical convention delegates', () => {
  const payload = {...base, items:[], delegates:null, threshold:null,
    delegateApplicability:'not-applicable-congressional-primary', delegateContests:[{
      id:'US:DEM:2024', year:2024, party:'DEM', candidate:'Candidate', delegates:4567,
      eventDate:'2024-08-05', basis:'convention-roll-call-votes', delegateType:'pledged-and-automatic-participating',
      url:'https://example.test/result', threshold:null,
    }]};
  expect(nomination(payload)).toBe(true);
  expect(nomination({...payload,delegateContests:[{...payload.delegateContests[0],delegates:'4567'}]})).toBe(false);
});

it('accepts evidenced pending certification and rejects an unknown status', () => {
  const row = {id:'NC', jurisdiction:'US-NC', electionDate:'2026-11-03', status:'pending',
    scheduledDate:'2026-11-24', scheduledTime:'11:00', timeZone:'America/New_York',url:'https://example.test/notice',certifiedAt:null};
  expect(election({...base,polls:[],results:[],certifications:[row]})).toBe(true);
  expect(election({...base,polls:[],results:[],certifications:[{...row,status:'winner-called'}]})).toBe(false);
});

it('accepts legal empty lists and refuses malformed finance and confirmation facts', () => {
  expect(finance({...base,items:[],independentExpenditures:[],filingRevisions:[]})).toBe(true);
  expect(finance({...base,items:[],independentExpenditures:[{id:'x',amount:'12'}]})).toBe(false);
  expect(appointments({...base,items:[],confirmations:[],hearings:[]})).toBe(true);
  expect(appointments({...base,items:[],confirmations:[{id:'x',confirmedAt:2026}],hearings:[]})).toBe(false);
  expect(appointments({...base,items:[],confirmations:[],hearings:[{id:'x',heldDates:'2026-03-05'}]})).toBe(false);
});
