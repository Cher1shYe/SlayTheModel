import {test} from 'node:test';
import assert from 'node:assert/strict';
import {aggregateHistory} from './history.mjs';

test('dense alternating samples become time-bucket averages while preserving the raw peak',()=>{
  const start=Date.UTC(2026,8,7);
  const rows=Array.from({length:1440},(_,i)=>({time:start+i*60000,count:i%2?100:0}));
  const result=aggregateHistory(rows,24,240);
  assert.equal(result.intervalMs,10*60000);
  assert.equal(result.history.length,144);
  assert.ok(result.history.every(p=>p.count===50&&p.samples===10));
  assert.equal(result.historyPeak,100);
  assert.equal(result.history[0].start,start);
  assert.equal(result.history[0].end,start+9*60000);
  assert.equal(rows.length,1440);
});
test('larger windows and narrower viewports merge more samples',()=>{
  const rows=Array.from({length:43200},(_,i)=>({time:i*60000,count:10}));
  const wide=aggregateHistory(rows,720,240);
  const narrow=aggregateHistory(rows,720,48);
  assert.ok(wide.history.length<=240);
  assert.ok(narrow.history.length<=48);
  assert.ok(narrow.intervalMs>wide.intervalMs);
  assert.equal(aggregateHistory(rows.slice(0,60),1,240).history.length,60);
});
test('gaps split buckets instead of interpolating missing samples; zero remains data',()=>{
  const result=aggregateHistory([{time:0,count:0},{time:60000,count:2},{time:300000,count:8}],24,240);
  assert.equal(result.history.length,2);
  assert.equal(result.history[0].count,1);
  assert.equal(result.history[1].breakBefore,true);
  assert.equal(result.history[1].samples,1);
  assert.equal(result.history[1].count,8);
  assert.deepEqual(aggregateHistory([],1,240).history,[]);
});
