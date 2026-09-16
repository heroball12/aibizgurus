import test from 'node:test';
import assert from 'node:assert/strict';
import {validPage,followupDraft,isUserCaption} from '../../static/js/concierge-actions.js';

test('model navigation cannot escape the explicit directory',()=>{
  const pages={pricing:{path:'/pricing/'}};
  assert.equal(validPage(pages,'pricing'),'pricing');
  for(const path of ['https://evil.example','//evil.example','__proto__','constructor','/admin/',null,{},['pricing']])assert.equal(validPage(pages,path),null);
});
test('draft tool cannot submit, check consent, set hidden fields or exceed field limits',()=>{
  const result=followupDraft({name:'a'.repeat(200),email:'customer@example.com',consent:true,submission_id:'x',website:'spam',message:'<script>alert(1)</script>'});
  assert.equal(result.name.length,150);
  assert.equal(result.email,'customer@example.com');
  assert.deepEqual(Object.keys(result).sort(),['email','message','name']);
  assert.equal(result.message,'<script>alert(1)</script>'); // Applied only through input.value, never HTML.
  assert.deepEqual(followupDraft({name:{x:1}}),{});
});
test('Runway user turns are labelled You even though the agent publishes the transcript',()=>{
  assert.equal(isUserCaption({id:'runway-transcription-user-3',participantIdentity:'avatar-agent'}),true);
  assert.equal(isUserCaption({id:'runway-transcription-assistant-3',participantIdentity:'avatar-agent'}),false);
  assert.equal(isUserCaption({local:true}),true);
});
