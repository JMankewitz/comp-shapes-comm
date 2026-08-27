import { assignSet, targetFor } from './src/exp2.js';

// Minimal stand-ins for the Empirica scopes assignSet touches.
const mkGlobals = () => { let store={}; return { get:(k)=>store[k], set:(k,v)=>{store[k]=v} }; };
const mkGame = (cond,id='g') => ({ id, get:(k)=> k==='contextStructure'?cond:undefined });

let fails=0;
const eq=(got,want,label)=>{ const ok=JSON.stringify(got)===JSON.stringify(want);
  if(!ok){fails++;console.log(`  FAIL ${label}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`);}
  else console.log(`  ok   ${label}`); };

// Run N dyads of one condition, return the sequence of setIds assigned.
const run = (schedule, cond, n, globals=mkGlobals()) => {
  const out=[];
  for(let i=0;i<n;i++) out.push(assignSet(mkGame(cond), schedule, globals).setId);
  return out;
};

const V1 = { schema_version:'exp2-schedule-1', set_ids:[0,1,2,3], dyads_per_condition_per_set:2 };

console.log('\n1. v1 schedule: behaviour must be IDENTICAL to before (depth-first, 2 per set)');
eq(run(V1,'comp-within',8), [0,0,1,1,2,2,3,3], 'fills depth-first, 2 each');
eq(run(V1,'comp-within',10).slice(8), [0,1], 'wraps onto least-filled after all full');

console.log('\n2. conditions tally independently');
{ const g=mkGlobals();
  eq(run(V1,'comp-within',2,g), [0,0], 'comp-within takes set 0');
  eq(run(V1,'comp-between',2,g), [0,0], 'comp-between also starts at set 0'); }

console.log('\n3. v2 targets: backfill one dyad on set 1, set 0 finished');
const V2 = { schema_version:'exp2-schedule-2', set_ids:[0,1,2,3], dyads_per_condition_per_set:2,
             targets:{ 'comp-between':{ '0':0, '1':1 } } };
eq(targetFor(V2,'comp-between',0), 0, 'target 0 for finished set');
eq(targetFor(V2,'comp-between',1), 1, 'target 1 for backfill set');
eq(targetFor(V2,'comp-between',2), 2, 'unlisted set falls back to default 2');
eq(targetFor(V2,'comp-within',0), 2, 'other condition unaffected by the map');
eq(run(V2,'comp-between',5), [1,2,2,3,3], 'skips set 0, takes exactly 1 on set 1');
eq(run(V2,'comp-within',4), [0,0,1,1], 'comp-within still fills set 0 normally');

console.log('\n4. surplus never lands on a zeroed (finished) set');
{ const many = run(V2,'comp-between',9);
  eq(many.slice(5).includes(0), false, 'wrap avoids the target-0 set'); }

console.log('\n5. replicate/slot arithmetic survives target 1 and target 0');
{ const g=mkGlobals();
  const a=assignSet(mkGame('comp-between'),V2,g);        // set 1, target 1
  eq([a.setId,a.setTarget,a.replicate,a.slotInReplicate,a.wrapped],[1,1,0,0,false],'first dyad on a target-1 set is replicate 0');
  const b=assignSet(mkGame('comp-between'),V2,g);        // set 1 now full -> set 2
  eq([b.setId,b.setTarget,b.replicate],[2,2,0],'moves on once the 1 is met'); }

console.log('\n6. all targets zero: still assigns rather than crashing a live game');
{ const Z={schema_version:'exp2-schedule-2',set_ids:[0,1],dyads_per_condition_per_set:2,
           targets:{'noncomp':{'0':0,'1':0}}};
  const r=assignSet(mkGame('noncomp'),Z,mkGlobals());
  eq([Number.isFinite(r.replicate), r.setId!==undefined],[true,true],'finite replicate, a set is returned'); }

console.log(fails? `\n${fails} FAILED` : '\nall assertions passed');
process.exit(fails?1:0);
