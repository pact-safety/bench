import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const template = readFileSync(new URL('../../templates/track_exam.html', import.meta.url), 'utf8');
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
class Field extends EventTarget {
  constructor(value='') {super();this.value=value;this.checked=false;this.required=false;this.dataset={};this.textContent='';}
  focus() {this.focused=true;}
}
function page() {
  const fields = Object.fromEntries(['track-exam-form','exam-answers','exam-modality','exam-transcript-confirmed','exam-status'].map(id=>[id,new Field()]));
  for (const id of Object.keys(fields)) assert.ok(template.includes(`id="${id}"`));
  fields['exam-modality'].value='written';
  vm.runInNewContext(script,{document:{getElementById:id=>fields[id]}});
  return {fields,submit(){const e=new Event('submit',{cancelable:true});fields['track-exam-form'].dispatchEvent(e);return e;}};
}

test('oral response requires explicit confirmation and any edit invalidates it',()=>{
  const {fields,submit}=page(); const modality=fields['exam-modality'], confirmed=fields['exam-transcript-confirmed'];
  modality.value='oral'; modality.dispatchEvent(new Event('change'));
  assert.equal(confirmed.required,true); assert.equal(submit().defaultPrevented,true);
  assert.match(fields['exam-status'].textContent,/confirm/);
  confirmed.checked=true; assert.equal(submit().defaultPrevented,false);
  fields['exam-answers'].dispatchEvent(new Event('input'));
  assert.equal(confirmed.checked,false); assert.equal(submit().defaultPrevented,true);
});

test('recording or pending transcription cannot submit; written fallback retains draft',()=>{
  const {fields,submit}=page(), answers=fields['exam-answers']; answers.value='Typed reasoning';
  answers.dataset.voiceNoteBusy='1'; answers.dispatchEvent(new Event('voice-note-state'));
  assert.equal(fields['exam-modality'].value,'oral'); assert.equal(submit().defaultPrevented,true);
  answers.dataset.voiceNoteBusy='0'; answers.dispatchEvent(new Event('voice-note-state'));
  fields['exam-modality'].value='written'; fields['exam-modality'].dispatchEvent(new Event('change'));
  assert.equal(fields['exam-transcript-confirmed'].required,false);
  assert.equal(submit().defaultPrevented,false);assert.equal(answers.value,'Typed reasoning');
});
