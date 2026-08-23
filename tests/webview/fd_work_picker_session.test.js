const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function harness() {
  const nodes = new Map();
  const docListeners = new Map();
  let liveInput = null;
  let liveWrapper = null;
  let livePopup = null;
  const calls = [];
  class E {
    constructor(tag='div') { this.tagName=tag.toUpperCase(); this.id=''; this.children=[]; this.parentElement=null; this.textContent=''; this.innerText=''; this.disabled=false; this.isConnected=true; this.attrs={}; this.listeners={}; this.classList={contains:(name)=>String(this.attrs.class||'').split(/\s+/).includes(name)}; }
    setAttribute(k,v){ this.attrs[k]=String(v); if(k==='id'){this.id=String(v); nodes.set(this.id,this);} }
    getAttribute(k){ return this.attrs[k] ?? null; }
    appendChild(c){ c.parentElement=this; this.children.push(c); if(c.id)nodes.set(c.id,c); return c; }
    remove(){ this.isConnected=false; if(this.id)nodes.delete(this.id); }
    addEventListener(n,fn){ (this.listeners[n]??=[]).push(fn); }
    dispatch(n){ for(const fn of (this.listeners[n]||[])) fn({target:this,preventDefault(){},stopImmediatePropagation(){}}); }
    contains(n){ if(n===this)return true; return this.children.some(c=>c.contains&&c.contains(n)); }
    closest(sel){ if(sel==='.ant-select') return this===liveInput?liveWrapper:null; if(sel==="[role='listbox']") return this._listbox||null; if(sel.includes('option') && this.getAttribute('role')==='option') return this; return null; }
    querySelector(sel){ if(this===liveWrapper && /selection-item/.test(sel)) return this._selected||null; return null; }
    querySelectorAll(sel){ if(this===livePopup && sel.includes("aria-selected='true'")) return (this._options||[]).filter(o=>o.getAttribute('aria-selected')==='true'); return []; }
    getClientRects(){ return [1]; }
  }
  const body=new E('body'), head=new E('head'), root=new E('html');
  const document={body,head,documentElement:root,readyState:'complete',createElement:(tag)=>new E(tag),getElementById:(id)=>nodes.get(id)||null,querySelector:(sel)=> sel==='#basic_caseId'?liveInput: sel==='#basic_caseId_list'?livePopup:null,addEventListener:(n,fn)=>{(docListeners.get(n)||docListeners.set(n,[]).get(n)).push(fn)},removeEventListener:(n,fn)=>{docListeners.set(n,(docListeners.get(n)||[]).filter(x=>x!==fn))}};
  const api={submit_case_picker_confirmation:(nonce,label,rev)=>{calls.push(['confirm',nonce,label,rev]); return Promise.resolve({ok:true,accepted:true});},submit_case_picker_cancellation:(nonce)=>{calls.push(['cancel',nonce]); return Promise.resolve({ok:true,accepted:true});},submit_adapter_action_result:()=>Promise.resolve({ok:true,accepted:true})};
  const window={document,location:{origin:'https://work.fangdalaw.com'},top:null,pywebview:{api},getComputedStyle:()=>({display:'block',visibility:'visible'}),addEventListener(){},removeEventListener(){}}; window.top=window;
  const context={window,document,Promise,setTimeout,clearTimeout,requestAnimationFrame:(cb)=>setTimeout(cb,0)};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../worktrace/integrations/fd_work/fd_work_picker_session.js'),'utf8'),context);
  function setCase(label){
    const input=new E('input'); input.setAttribute('id','basic_caseId'); input.setAttribute('aria-controls','basic_caseId_list'); input.setAttribute('aria-expanded','true');
    const wrapper=new E(); wrapper.attrs.class='ant-select'; const popup=new E(); popup.setAttribute('id','basic_caseId_list'); popup.setAttribute('role','listbox');
    if(label){ const selected=new E(); selected.attrs.class='ant-select-selection-item'; selected.setAttribute('title',label); selected.textContent=label; wrapper._selected=selected; const option=new E(); option.setAttribute('role','option'); option.setAttribute('title',label); option.setAttribute('aria-selected','true'); option.textContent=label; option._listbox=popup; popup._options=[option]; } else { wrapper._selected=null; popup._options=[]; }
    liveInput=input; liveWrapper=wrapper; livePopup=popup; return {input,wrapper,popup};
  }
  return {context,setCase,calls,nodes,docListeners};
}

const contract={version:5,operation_nonce:'nonce',operation_generation:7,max_label_length:100,field:{selector:'#basic_caseId',listbox:'#basic_caseId_list'}};

test('live DOM replacement remains selectable and candidate does not block page', async()=>{ const h=harness(); h.setCase('INITIAL'); assert.equal(h.context.window.WorkTraceFDWorkPickerSession.enterCasePicker(contract).ok,true); h.setCase('CASE B'); h.context.window.WorkTraceFDWorkPickerSession._test.startMouseCommit('CASE B'); await new Promise(r=>setTimeout(r,30)); const state=h.context.window.WorkTraceFDWorkPickerSession._test.state(); assert.equal(state.state,'candidate'); assert.equal(state.candidate.label,'CASE B'); assert.equal(h.nodes.has('worktrace-fdwork-picker-blocker'),false); });
test('latest selection wins when an earlier reconciliation is still pending', async()=>{ const h=harness(); h.setCase('INITIAL'); h.context.window.WorkTraceFDWorkPickerSession.enterCasePicker(contract); h.setCase(null); h.context.window.WorkTraceFDWorkPickerSession._test.startMouseCommit('CASE A'); h.setCase('CASE B'); h.context.window.WorkTraceFDWorkPickerSession._test.startMouseCommit('CASE B'); await new Promise(r=>setTimeout(r,30)); const state=h.context.window.WorkTraceFDWorkPickerSession._test.state(); assert.equal(state.candidate.label,'CASE B'); assert.equal(state.revision,1); });
test('confirm binds proof to current candidate and only then installs blocker', async()=>{ const h=harness(); h.setCase(null); h.context.window.WorkTraceFDWorkPickerSession.enterCasePicker(contract); h.setCase('CASE C'); h.context.window.WorkTraceFDWorkPickerSession._test.startMouseCommit('CASE C'); await new Promise(r=>setTimeout(r,30)); const toolbar=h.nodes.get('worktrace-fdwork-picker-toolbar'); toolbar._confirm.dispatch('click'); await Promise.resolve(); assert.deepEqual(h.calls[0],['confirm','nonce','CASE C',1]); assert.equal(h.nodes.has('worktrace-fdwork-picker-blocker'),true); assert.match(h.nodes.get('worktrace-fdwork-picker-blocker').textContent,/正在确认案件/); });
test('keyboard Enter creates proof after a real committed selection', async()=>{ const h=harness(); h.setCase(null); h.context.window.WorkTraceFDWorkPickerSession.enterCasePicker(contract); h.setCase('CASE K'); h.context.window.WorkTraceFDWorkPickerSession._test.startKeyboardCommit(); await new Promise(r=>setTimeout(r,30)); assert.equal(h.context.window.WorkTraceFDWorkPickerSession._test.state().candidate.label,'CASE K'); });
test('twenty enter/leave cycles release delegated listeners',()=>{ const h=harness(); h.setCase(null); for(let i=0;i<20;i++){ h.context.window.WorkTraceFDWorkPickerSession.enterCasePicker(contract); h.context.window.WorkTraceFDWorkPickerSession.leaveCasePicker(); } for(const values of h.docListeners.values()) assert.equal(values.length,0); });
