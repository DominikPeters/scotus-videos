'use strict';
const assert=require('node:assert/strict');
const {reminderWindow,splitReminderEvent}=require('../render/subscribe');
assert.deepEqual(reminderWindow([],1000),{start:600,end:608});
assert.equal(reminderWindow([],614.95),null);
assert.deepEqual(reminderWindow([],615),{start:600,end:608});
assert.deepEqual(reminderWindow([{start:590,end:605},{start:619,end:640}],700),{start:640,end:648});
assert.deepEqual(reminderWindow([{start:615,end:640}],700),{start:600,end:608});
assert.deepEqual(reminderWindow([{start:640,end:660},{start:590,end:620},{start:610,end:645}],675),{start:660,end:668});
assert.equal(reminderWindow([{start:600,end:690}],700),null);
assert.deepEqual(reminderWindow([{start:600,end:620}],700,{cardTransition:1.2}),{start:621.2,end:629.2});
assert.throws(()=>reminderWindow([{start:10,end:NaN}],1000));
const base={first_frame:11990,end_frame:12170,ops:[{name:'nextTextBlock'}]},window={start:600,end:608};
const events=splitReminderEvent(base,window,599.5);
assert.equal(events[0].first_frame,base.first_frame);assert.equal(events.at(-1).end_frame,base.end_frame);
for(let i=1;i<events.length;i++)assert.equal(events[i-1].end_frame,events[i].first_frame);
assert.equal(events.flatMap(e=>e.ops).filter(o=>o.name==='nextTextBlock').length,1);
assert.equal(events.find(e=>e.first_frame===12000).ops.at(-1).args[0],0);
assert.equal(events.find(e=>e.first_frame===12160).ops.at(-1).args[0],8);
// Splitting a long still preserves the exact eight-second visible interval.
let elapsed=-1,visible=0;
for(const e of events){for(const op of e.ops)if(op.name==='setSubscribeReminderProgress')elapsed=op.args[0];if(elapsed>=0&&elapsed<8)visible+=e.end_frame-e.first_frame;}
assert.equal(visible,160);
// A parallel chunk reconstructs the same reminder state by replaying earlier ops.
const chunkStart=12035;
let replay=-1;for(const e of events){for(const op of e.ops)if(op.name==='setSubscribeReminderProgress')replay=op.args[0];if(e.end_frame>chunkStart)break;}
assert.equal(replay,.4);
assert.deepEqual(splitReminderEvent(base,null,599.5),[base]);
const zero={first_frame:12160,end_frame:12160,ops:[{name:'scrollTranscript'}]};
assert.equal(splitReminderEvent(zero,window,608)[0].ops.at(-1).args[0],8);
console.log('Passed gap selection, overlap merging, exact boundaries, fade frames, operation preservation and parallel replay.');
