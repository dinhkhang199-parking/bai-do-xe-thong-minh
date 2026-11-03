const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../frontend/web/app.js'), 'utf8');
const cameraSource = fs.readFileSync(path.join(__dirname, '../frontend/web/camera.js'), 'utf8');
const billingSource = fs.readFileSync(path.join(__dirname, '../frontend/web/billing-ui.js'), 'utf8');
const mbSource = fs.readFileSync(path.join(__dirname, '../frontend/web/mb-ui.js'), 'utf8');
const autoSource = fs.readFileSync(path.join(__dirname, '../frontend/web/auto-quick-ui.js'), 'utf8');
function element(extra = {}) {
  return { innerHTML: '', textContent: '', hidden: false, value: '', disabled: false, dataset: {}, options: [],
    focus() { this.focused = true; }, click() { return this.listeners.click?.(); }, showModal() { this.open = true; this.modalCount = (this.modalCount || 0) + 1; }, close() { this.open = false; },
    listeners: {}, setAttribute(name, value) { (this.attributes ||= {})[name] = value; }, addEventListener(name, handler) { this.listeners[name] = handler; },
    classList: { add() {}, remove() {}, toggle() {} }, ...extra };
}
function setup(fixtures = {}, overrides = {}) {
  const nodes = {}, lists = {}, requests = [], revoked = [];
  const get = selector => nodes[selector] ||= element();
  const context = vm.createContext({
    document: { querySelector: get, querySelectorAll: selector => lists[selector] || [], addEventListener() {}, removeEventListener() {} },
    localStorage: { getItem() { return ''; }, setItem() {}, removeItem() {} }, AbortController, FormData, URLSearchParams,
    URL: { createObjectURL() { return 'blob:test-preview'; }, revokeObjectURL(url) { revoked.push(url); } },
    setTimeout() { return 1; }, clearTimeout() {}, confirm: () => true, prompt: () => null,
    fetch: async (url, options) => {
      requests.push({url,options});let payload=fixtures[url];
      if(!payload&&url.startsWith('/tickets/active?')&&fixtures['/tickets/active']){
        const params=new URLSearchParams(url.split('?')[1]),key=value=>String(value||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
        let rows=fixtures['/tickets/active'].items||[];
        if(params.has('plate'))rows=rows.filter(row=>key(row.plate_entry)===key(params.get('plate')));
        if(params.get('q'))rows=rows.filter(row=>key(row.plate_entry).includes(key(params.get('q')))||key(row.ticket_id).includes(key(params.get('q'))));
        const offset=Number(params.get('offset')||0),limit=Number(params.get('limit')||50);
        payload={items:rows.slice(offset,offset+limit),total:rows.length};
      }
      return {ok:true,json:async()=>payload||{}};
    },
    ...overrides,
  });
  vm.runInContext(cameraSource, context);
  vm.runInContext(mbSource, context);
  vm.runInContext(autoSource, context);
  vm.runInContext(billingSource, context);
  vm.runInContext(source + '\nthis.ui = { state, RENDER, bindUpload, runPending, api, previewCleanups, requestReauthentication, doSessionLogin, doLogin, realShowView:showView, workflowDrafts, logFilters, bindTicketSearch, bindLiveTicketSearch };', context);
  context.ui.state.user = { username: 'admin', role: 'admin' };
  if(!overrides.enableAutomaticOCR){
    // Existing unit cases isolate manual confirmation from automatic scanning.
    vm.runInContext('const unitBindUpload=bindUpload;bindUpload=(prefix,options={})=>unitBindUpload(prefix,{...options,autoScan:false});',context);
  }
  vm.runInContext('showView = async () => {};', context);
  return { ...context.ui, context, get, nodes, lists, requests, revoked };
}

function workflow(ui, prefix) {
  const zone = element();
  ui.get('#' + prefix + '-drop').closest = () => zone;
  return zone;
}
function choosePhoto(zone, name = 'dummy.jpg') {
  const file = new File(['dummy photo'], name, {type:'image/jpeg'});
  zone.listeners.drop({preventDefault(){},dataTransfer:{files:[file]}});
  return file;
}

test('switching account during reauthentication clears the previous operators photos and scan tokens',async()=>{
  const ui=setup({'/auth/login':{access_token:'new-user-token',user:{username:'operator',role:'operator'}}});
  const zone=workflow(ui,'entry');ui.state.view='entry';await ui.RENDER.entry();choosePhoto(zone);
  ui.get('#entry-plate').value='54-L1 9999';ui.workflowDrafts.entry.scanData={token:'old-user-scan'};
  ui.requestReauthentication();ui.get('#session-username').value='operator';ui.get('#session-password').value='fixture';
  await ui.doSessionLogin({preventDefault(){}});
  assert.equal(ui.state.user.username,'operator');assert.equal(ui.workflowDrafts.entry.file,null);
  assert.equal(ui.workflowDrafts.entry.plate,'');assert.equal(ui.workflowDrafts.entry.scanData,undefined);
  assert.equal(ui.revoked.length,1);
});

test('explicit account switch clears drafts but waits for an in-flight vehicle write',async()=>{
  let reloads=0;const ui=setup({}, {location:{reload(){reloads++;}}});
  const zone=workflow(ui,'entry');ui.state.view='entry';await ui.RENDER.entry();choosePhoto(zone);
  ui.workflowDrafts.entry.scanData={token:'fixture-scan'};ui.state.workflowPending=true;
  vm.runInContext('logout()',ui.context);assert.equal(reloads,0);assert.ok(ui.workflowDrafts.entry.file);
  ui.state.workflowPending=false;vm.runInContext('logout()',ui.context);
  assert.equal(reloads,1);assert.equal(ui.workflowDrafts.entry.file,null);
  assert.equal(ui.workflowDrafts.entry.scanData,undefined);assert.equal(ui.state.user,null);
});

test('a success from the old account is ignored after the token changes',async()=>{
  let finish;const ui=setup({}, {fetch:()=>new Promise(resolve=>finish=resolve)});ui.state.token='old';
  const pending=ui.api('/logs');ui.state.token='new';finish({ok:true,json:async()=>({items:[{ticket_id:'OLD'}]})});
  await assert.rejects(pending,error=>error.name==='AbortError');
});

test('uncertain administration writes ask to check state and are never retried',async()=>{
  let calls=0;const ui=setup({}, {fetch:async()=>{calls++;return {ok:true,json:async()=>{throw new SyntaxError('bad response');}};}});
  await assert.rejects(ui.api('/admin/users/worker/role',{method:'PATCH'}),/Kiểm tra trạng thái/);
  assert.equal(calls,1);
});

test('validation errors identify the field and server failures expose their safe reference',async()=>{
  const ui=setup({}, {fetch:async()=>({ok:false,status:422,json:async()=>({detail:[{loc:['body','vehicle_type'],input:'PRIVATE'}]})})});
  await assert.rejects(ui.api('/vehicle/entry',{method:'POST'}),error=>/loại xe/.test(error.message)&&!error.message.includes('PRIVATE'));
  ui.context.fetch=async()=>({ok:false,status:500,headers:{get:()=> 'fixture-reference'},json:async()=>({error:{message:'Máy chủ gặp lỗi.'}})});
  await assert.rejects(ui.api('/logs'),/fixture-reference/);
});

test('parking timestamps use Vietnam time even on a computer configured for UTC',()=>{
  const previous=process.env.TZ;process.env.TZ='UTC';
  try{
    const ui=setup();
    assert.match(vm.runInContext("formatTime('2026-11-03 08:00:00')",ui.context),/08:00/);
    assert.match(vm.runInContext("formatTime('2026-11-03T01:00:00Z')",ui.context),/08:00/);
  }finally{if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous;}
});

test('server ticket lookup finds a vehicle outside the first fifty tickets and keeps its letters distinct',async()=>{
  const rows=Array.from({length:120},(_,i)=>({ticket_id:'T'+i,plate_entry:i===110?'30-AB 123.45':i===111?'30-A8 123.45':`59-B1 ${10000+i}`,status:'IN_PARKING'}));
  const ui=setup({'/tickets/active':{items:rows}});ui.state.view='exit';
  const search=ui.bindLiveTicketSearch({items:rows.slice(0,50),total:120});
  ui.get('#exit-plate').value='30-AB 123.45';await search.matchPlate(ui.get('#exit-plate').value);
  assert.equal(ui.get('#exit-ticket').value,'T110');
  assert.match(ui.requests[0].url,/plate=30AB12345/);
  assert.equal(search.isPending(),false);
});

test('late ticket lookup cannot select a previous vehicles ticket',async()=>{
  const replies=[];const ui=setup({}, {fetch:()=>new Promise(resolve=>replies.push(resolve))});ui.state.view='exit';
  const search=ui.bindLiveTicketSearch({items:[],total:0});
  ui.get('#exit-plate').value='30-AB 123.45';const first=search.matchPlate('30-AB 123.45');
  ui.get('#exit-plate').value='30-A8 123.45';const second=search.matchPlate('30-A8 123.45');
  replies[1]({ok:true,json:async()=>({items:[{ticket_id:'NEW',plate_entry:'30-A8 123.45',status:'IN_PARKING'}],total:1})});await second;
  replies[0]({ok:true,json:async()=>({items:[{ticket_id:'OLD',plate_entry:'30-AB 123.45',status:'IN_PARKING'}],total:1})});await first;
  assert.equal(ui.get('#exit-ticket').value,'NEW');
});

test('refreshing the ticket list preserves the selected photo and manual plate',async()=>{
  const ui=setup({'/tickets/active':{items:[]}}),zone=workflow(ui,'exit');ui.state.view='exit';await ui.RENDER.exit();
  const photo=choosePhoto(zone);ui.get('#exit-plate').value='54-L1 9999';
  await ui.get('#exit-ticket-refresh').listeners.click();
  assert.equal(ui.workflowDrafts.exit.file,photo);assert.equal(ui.get('#exit-plate').value,'54-L1 9999');
});

test('ticket paging returns to the valid page if the last page shrinks',async()=>{
  const ui=setup({}, {fetch:async url=>({ok:true,json:async()=>url.includes('offset=50')?{items:[],total:1}:
    {items:[{ticket_id:'ONLY',plate_entry:'54-L1 9999',status:'IN_PARKING'}],total:1}})});
  ui.state.view='exit';ui.bindLiveTicketSearch({items:[],total:60});
  await ui.get('#exit-ticket-next').listeners.click();
  assert.match(ui.get('#exit-ticket-count').textContent,/1–1 \/ 1/);
  assert.equal(ui.get('#exit-ticket-prev').disabled,true);
  assert.match(ui.get('#exit-ticket').innerHTML,/ONLY/);
});

test('a failed ticket refresh preserves the draft and can recover on retry',async()=>{
  let fail=true;const ui=setup({}, {fetch:async()=>{
    if(fail)throw new Error('offline');
    return {ok:true,json:async()=>({items:[{ticket_id:'OK',plate_entry:'54-L1 9999',status:'IN_PARKING'}],total:1})};
  }});
  ui.state.view='exit';ui.workflowDrafts.exit.file=new File(['photo'],'fixture.jpg');
  const search=ui.bindLiveTicketSearch({items:[],total:60});ui.get('#exit-plate').value='54-L1 9999';
  await ui.get('#exit-ticket-refresh').listeners.click();
  assert.match(ui.get('#exit-ticket-count').textContent,/Chưa tải được/);assert.equal(search.isPending(),false);
  assert.equal(ui.workflowDrafts.exit.file.name,'fixture.jpg');
  fail=false;await ui.get('#exit-ticket-refresh').listeners.click();
  assert.equal(ui.get('#exit-ticket').value,'OK');assert.match(ui.get('#exit-ticket-count').textContent,/1–1/);
});

for(const ocr of [
  {text:'30-AB 123.45',is_usable:false,quality_note:'Ký tự chưa rõ'},
  {text:'30-AB 123.45',is_usable:true,ocr_disagreement:true},
  {text:'30-AB 123.45',is_usable:true,ambiguous:true,plate_count:2},
  {text:'30-AB 123.45'},
])test('automatic OCR does not apply uncertain result: '+JSON.stringify(ocr),async()=>{
  const ui=setup({'/ocr':{ocr,scan_token:'fixture'}},{enableAutomaticOCR:true});
  const zone=workflow(ui,'entry');ui.state.view='entry';await ui.RENDER.entry();choosePhoto(zone);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.get('#entry-plate').value,'');
  assert.match(ui.get('#entry-scan-result').innerHTML,/nhập tay/);
});

for(const prefix of ['entry','exit'])test(prefix+' cannot submit an in-flight OCR but can stop and enter manually',async()=>{
  let finish;
  const ui=setup({}, {enableAutomaticOCR:true,fetch:async(url,options)=>{
    ui.requests.push({url,options});
    if(url==='/ocr')return new Promise(resolve=>{finish=resolve;});
    return {ok:true,json:async()=>({items:[{ticket_id:'T1',plate_entry:'66-B1 069.99',status:'IN_PARKING'}]})};
  }});
  const zone=workflow(ui,prefix);ui.state.view=prefix;await ui.RENDER[prefix]();choosePhoto(zone);
  ui.get('#'+prefix+'-plate').value='66-B1 069.99';
  ui.get('#exit-ticket').value='T1';
  await ui.get('#'+prefix+'-submit').listeners.click();
  assert.equal(ui.requests.filter(r=>r.url.startsWith('/vehicle/')).length,0);
  ui.get('#'+prefix+'-cancel-scan').listeners.click();
  await ui.get('#'+prefix+'-submit').listeners.click();
  const write=ui.requests.find(r=>r.url==='/vehicle/'+prefix);
  assert.equal(write.options.body.get('manual_only'),'true');
  finish({ok:true,json:async()=>({ocr:{text:'99-Z9 999.99',is_usable:true},scan_token:'stale'})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.notEqual(ui.get('#'+prefix+'-plate').value,'99-Z9 999.99');
});

test('failed rescan clears the previous scan token',async()=>{
  let scans=0;
  const ui=setup({}, {fetch:async()=>{
    if(++scans>1)throw new Error('provider unavailable');
    return {ok:true,json:async()=>({ocr:{text:'66-B1 069.99',is_usable:true},scan_token:'old-token'})};
  }});
  const zone=workflow(ui,'entry'),upload=ui.bindUpload('entry');choosePhoto(zone);
  await ui.get('#entry-scan').listeners.click();
  assert.equal(upload.getScan().token,'old-token');
  await ui.get('#entry-scan').listeners.click();
  assert.equal(upload.getScan(),null);
  assert.equal(upload.isScanning(),false);
});

test('review pagination can reach tickets beyond the old 200 ticket limit',async()=>{
  const ui=setup({'/logs?status=NEEDS_REVIEW&limit=25&offset=200':{items:[{ticket_id:'OLDER-REVIEW',status:'NEEDS_REVIEW'}],total:225}});
  ui.state.view='review';vm.runInContext('reviewOffset=200',ui.context);await ui.RENDER.review();
  assert.match(ui.get('#view-content').innerHTML,/OLDER-REVIEW/);
  assert.match(ui.get('#view-content').innerHTML,/Trang 9 \/ 9/);
  await ui.get('#review-prev').listeners.click();
  assert.equal(vm.runInContext('reviewOffset',ui.context),175);
});

test('late dashboard response from an older render cannot replace a newer view',async()=>{
  const finish=[];const ui=setup({}, {fetch:()=>new Promise(resolve=>finish.push(resolve))});
  ui.state.view='dashboard';const pending=ui.RENDER.dashboard();ui.state.viewVersion++;
  ui.get('#view-content').innerHTML='new content';
  finish.forEach(resolve=>resolve({ok:true,json:async()=>({items:[],kpis:{}})}));await pending;
  assert.equal(ui.get('#view-content').innerHTML,'new content');
});

test('a stalled read times out and is never retried automatically',async()=>{
  let deadline,calls=0;
  const ui=setup({}, {setTimeout(fn,ms){if(ms===30000)deadline=fn;return 1;},clearTimeout(){},
    fetch:(_,options)=>{calls++;return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{const error=new Error('aborted');error.name='AbortError';reject(error);}));}});
  const pending=ui.api('/logs');deadline();await assert.rejects(pending,/phản hồi quá lâu/);assert.equal(calls,1);
});

test('navigation matches admin, operator and viewer permissions',()=>{
  const ui=setup();
  const views=['dashboard','entry','exit','payments','logs','review','admin','pricing','mb'];
  ui.lists['.nav-item']=views.map(view=>element({dataset:{view}}));
  for(const role of ['admin','operator','viewer']){
    ui.state.user.role=role;vm.runInContext('syncUserShell()',ui.context);
    const visible=ui.lists['.nav-item'].filter(e=>!e.hidden).map(e=>e.dataset.view);
    assert.deepEqual(visible,views.filter(view=>!(['entry','exit'].includes(view)&&role==='viewer')&&
      !(['admin','pricing','mb'].includes(view)&&role!=='admin')));
  }
});

test('viewer cannot navigate directly to write or administration screens',async()=>{
  const ui=setup();ui.state.user.role='viewer';let rendered=0;
  ui.RENDER.dashboard=async()=>{rendered++;};
  for(const name of ['entry','exit','admin','pricing','mb']){
    await ui.realShowView(name);assert.equal(ui.state.view,'dashboard');
  }
  assert.equal(rendered,5);
});

test('reauthentication with viewer rights leaves a previously writable screen',async()=>{
  const ui=setup({'/auth/login':{access_token:'fixture-new',user:{username:'admin',role:'viewer'}}});
  ui.context.showView=ui.realShowView;ui.RENDER.dashboard=async()=>{};
  ui.state.view='entry';ui.get('#session-username').value='admin';
  ui.get('#session-password').value='fixture';
  await ui.doSessionLogin({preventDefault(){}});
  assert.equal(ui.state.view,'dashboard');assert.equal(ui.state.user.role,'viewer');
  assert.equal(ui.get('#entry-submit').disabled,true);
});

test('account page prevents changing the current administrator and preserves the last active admin', async () => {
  const ui=setup({'/admin/users':{items:[{username:'admin',role:'admin',is_active:1},{username:'worker',role:'operator',is_active:1}]}});
  ui.state.view='admin';
  const ownSave=element({dataset:{u:'admin',op:'role'}});
  ui.lists['[data-op]']=[ownSave];
  await ui.RENDER.admin();
  assert.match(ui.get('#u-tbody').innerHTML,/data-role-user="admin" disabled/);
  assert.match(ui.get('#u-tbody').innerHTML,/data-u="admin" data-op="role" disabled/);
  assert.doesNotMatch(ui.get('#u-tbody').innerHTML,/data-role-user="worker" disabled/);
  await ownSave.listeners.click();
  assert.deepEqual(ui.requests.map(item=>item.url),['/admin/users']);
  ui.state.user.username='environment-admin';
  await ui.RENDER.admin();
  assert.match(ui.get('#u-tbody').innerHTML,/data-u="admin" data-op="delete" disabled/);
});

test('automatic entry scan fills the plate once and final confirmation reuses its token',async()=>{
  const ui=setup({'/ocr':{ocr:{text:'59-B1 123.45',is_usable:true},scan_token:'fixture-scan-token'},
    '/vehicle/entry':{result:{ticket_id:'T1',status:'IN_PARKING'}}},{enableAutomaticOCR:true});
  const zone=workflow(ui,'entry');ui.state.view='entry';await ui.RENDER.entry();choosePhoto(zone);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.get('#entry-plate').value,'59-B1 123.45');
  assert.doesNotMatch(ui.get('#entry-scan-result').innerHTML,/Dùng biển số đã đối chiếu/);
  await ui.get('#entry-submit').listeners.click();
  assert.deepEqual(ui.requests.map(r=>r.url),['/ocr','/vehicle/entry']);
  const body=ui.requests[1].options.body;
  assert.equal(body.get('scan_token'),'fixture-scan-token');
  assert.equal(body.get('ai_review_confirmed'),'true');
});

test('late automatic OCR does not overwrite an operator edit',async()=>{
  let finish;
  const ui=setup({}, {enableAutomaticOCR:true,fetch:()=>new Promise(resolve=>{finish=resolve;})});
  const zone=workflow(ui,'entry');ui.state.view='entry';await ui.RENDER.entry();choosePhoto(zone);
  ui.get('#entry-plate').value='30-AB 123.45';
  finish({ok:true,json:async()=>({ocr:{text:'30-A8 123.45',is_usable:true},scan_token:'fixture'})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.get('#entry-plate').value,'30-AB 123.45');
});

test('exit selects one exact plate match and preserves a manually chosen different ticket',async()=>{
  let lookup;
  const ui=setup({'/tickets/active':{items:[
    {ticket_id:'A',plate_entry:'30-AB 123.45',status:'IN_PARKING'},
    {ticket_id:'B',plate_entry:'30-A8 123.45',status:'IN_PARKING'}]},
    '/ocr':{ocr:{text:'30-AB 123.45',is_usable:true},scan_token:'fixture'}},{enableAutomaticOCR:true,setTimeout(fn,ms){if(ms===250)lookup=fn;return 1;}});
  const zone=workflow(ui,'exit');ui.state.view='exit';await ui.RENDER.exit();choosePhoto(zone);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.get('#exit-ticket').value,'A');
  ui.get('#exit-ticket-search').value='30a8';ui.get('#exit-ticket-search').listeners.input();await lookup();
  ui.get('#exit-ticket').value='B';ui.get('#exit-ticket').listeners.change();
  ui.get('#exit-plate').value='30-AB 123.45';ui.get('#exit-plate').listeners.input();
  assert.equal(ui.get('#exit-ticket').value,'B');
  assert.match(ui.get('#exit-match-note').textContent,/khác vé/);
});

test('navigation keeps independent in-memory entry and exit drafts and releases old previews', async () => {
  let stored = 0;
  const ui = setup({'/tickets/active':{items:[{ticket_id:'T1',status:'IN_PARKING'}]}}, {
    localStorage:{getItem(){return '';},setItem(){stored++;},removeItem(){}},
  });
  const entryZone = workflow(ui,'entry'), exitZone = workflow(ui,'exit');
  ui.state.view='entry'; await ui.RENDER.entry();
  const file = choosePhoto(entryZone);
  ui.get('#entry-plate').value='30-AB 123.45';
  ui.previewCleanups.splice(0).forEach(fn=>fn());
  ui.state.view='exit'; await ui.RENDER.exit();
  choosePhoto(exitZone,'exit.jpg');
  ui.get('#exit-plate').value='30-A8 123.45'; ui.get('#exit-ticket').value='T1';
  ui.previewCleanups.splice(0).forEach(fn=>fn());
  ui.state.view='entry'; await ui.RENDER.entry();
  assert.equal(ui.workflowDrafts.entry.file,file);
  assert.equal(ui.get('#entry-plate').value,'30-AB 123.45');
  assert.equal(ui.get('#entry-filename').textContent,'dummy.jpg');
  assert.equal(ui.workflowDrafts.exit.file.name,'exit.jpg');
  assert.equal(ui.workflowDrafts.exit.ticket,'T1');
  assert.equal(stored,0);
  assert.equal(ui.revoked.length,2);
  ui.get('#entry-reset').listeners.click();
  assert.equal(ui.workflowDrafts.entry.file,null);
  assert.equal(ui.workflowDrafts.entry.plate,'');
});

test('ticket search ignores separators, keeps letters distinct, and never auto-selects a vehicle', () => {
  const ui=setup();
  ui.bindTicketSearch([
    {ticket_id:'A',plate_entry:'30-AB 123.45'},
    {ticket_id:'B',plate_entry:'30-A8 123.45'},
  ]);
  ui.get('#exit-ticket-search').value='30ab12345'; ui.get('#exit-ticket-search').listeners.input();
  assert.match(ui.get('#exit-ticket').innerHTML, /value="A"/);
  assert.doesNotMatch(ui.get('#exit-ticket').innerHTML, /value="B"/);
  assert.equal(ui.get('#exit-ticket').value,'');
  ui.get('#exit-ticket').value='A'; ui.get('#exit-ticket').listeners.change();
  ui.get('#exit-ticket-search').value='missing'; ui.get('#exit-ticket-search').listeners.input();
  assert.equal(ui.get('#exit-ticket').value,'');
  assert.equal(ui.get('#exit-ticket').disabled,true);
  ui.get('#exit-ticket-search').value=''; ui.get('#exit-ticket-search').listeners.input();
  assert.equal(ui.get('#exit-ticket').disabled,false);
});

test('OCR use is explicit, never submits, and an old OCR button cannot apply to a new photo', async () => {
  const ui=setup({'/ocr':{ocr:{text:'30-AB 123.45',is_usable:true}}});
  const zone=workflow(ui,'entry'); ui.state.view='entry'; await ui.RENDER.entry();
  choosePhoto(zone); await ui.get('#entry-scan').listeners.click();
  assert.equal(ui.get('#entry-plate').value,'');
  const use = ui.get('#entry-use-scan').listeners.click;
  use();
  assert.equal(ui.get('#entry-plate').value,'30-AB 123.45');
  assert.equal(ui.requests.length,1);
  choosePhoto(zone,'next.jpg'); ui.get('#entry-plate').value='new draft';
  use();
  assert.equal(ui.get('#entry-plate').value,'new draft');
});

test('missing photo is explained inline and focuses the upload control', async () => {
  const ui=setup(); workflow(ui,'entry'); ui.state.view='entry'; await ui.RENDER.entry();
  await ui.get('#entry-submit').listeners.click();
  assert.equal(ui.get('#entry-error').hidden,false);
  assert.match(ui.get('#entry-error').textContent,/Chọn ảnh/);
  assert.equal(ui.get('#entry-drop').focused,true);
  assert.equal(ui.requests.length,0);
});

test('changing a selected photo clears the previous manual correction', async () => {
  const ui=setup(); const zone=workflow(ui,'entry');
  ui.state.view='entry'; await ui.RENDER.entry(); choosePhoto(zone);
  ui.get('#entry-plate').value='30-AB 123.45'; ui.get('#entry-plate').listeners.input();
  choosePhoto(zone,'other-car.jpg');
  assert.equal(ui.get('#entry-plate').value,'');
  assert.equal(ui.workflowDrafts.entry.plate,'');
});

test('a stalled write unlocks the workflow without retrying and asks to check the journal', async () => {
  let deadline, calls=0;
  const ui=setup({}, {
    setTimeout(fn,ms){if(ms===90000)deadline=fn;return 1;},clearTimeout(){},
    fetch:async(url,options)=>{
      calls++;
      return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{
        const error=new Error('aborted'); error.name='AbortError'; reject(error);
      }));
    },
  });
  const zone=workflow(ui,'entry'); ui.state.view='entry'; await ui.RENDER.entry(); choosePhoto(zone);
  ui.get('#entry-plate').value='59-B1 123.45';
  const pending=ui.get('#entry-submit').listeners.click();
  deadline(); await pending;
  assert.equal(ui.state.workflowPending,false); assert.equal(ui.get('#entry-submit').disabled,false);
  assert.equal(calls,1); assert.match(ui.get('#entry-error').textContent,/Kiểm tra Nhật ký/);
  assert.equal(ui.workflowDrafts.entry.file.name,'dummy.jpg');
});

test('failed submission preserves the draft and leaves a persistent inline retry message', async () => {
  const ui=setup({}, {fetch:async()=>{throw new Error('offline');}});
  const zone=workflow(ui,'entry'); ui.state.view='entry'; await ui.RENDER.entry();
  choosePhoto(zone); ui.get('#entry-plate').value='30-AB 123.45';
  await ui.get('#entry-submit').listeners.click();
  assert.match(ui.get('#entry-error').textContent,/Kiểm tra kết nối/);
  assert.equal(ui.get('#entry-submit').disabled,false);
  assert.equal(ui.get('#entry-plate').value,'30-AB 123.45');
  assert.equal(ui.workflowDrafts.entry.file.name,'dummy.jpg');
});

test('pending entry blocks navigation and double submission until its result arrives', async () => {
  let release, calls=0;
  const ui=setup({}, {fetch:async()=>{calls++; return new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({result:{ticket_id:'T1'}})});});}});
  const zone=workflow(ui,'entry'); ui.state.view='entry'; await ui.RENDER.entry(); choosePhoto(zone);
  ui.get('#entry-plate').value='59-B1 123.45';
  const pending=ui.get('#entry-submit').listeners.click();
  await ui.get('#entry-submit').listeners.click();
  await ui.realShowView('logs');
  assert.equal(ui.state.view,'entry'); assert.equal(calls,1);
  release(); await pending;
  assert.equal(ui.state.workflowPending,false);
});

test('a mismatched exit is announced as awaiting review with a direct review action', async () => {
  const ui=setup({'/tickets/active':{items:[{ticket_id:'T1',status:'IN_PARKING'}]},
    '/vehicle/exit':{result:{status:'NEEDS_REVIEW',match_result:'MISMATCH'}}});
  const zone=workflow(ui,'exit'); ui.state.view='exit'; await ui.RENDER.exit();
  choosePhoto(zone); ui.get('#exit-ticket').value='T1';
  ui.get('#exit-plate').value='59-B1 123.45';
  await ui.get('#exit-submit').listeners.click();
  assert.match(ui.get('#exit-result').innerHTML,/chưa duyệt xe ra/);
  assert.match(ui.get('#exit-result').innerHTML,/Kiểm tra vé ngay/);
  assert.match(ui.get('#toast').className,/warning/);
  assert.equal(ui.get('#exit-submit').disabled,true);
});

test('finishing a manually selected exit clears the old match and allows the next vehicle to match automatically', async () => {
  let lookup;
  const ui=setup({'/tickets/active':{items:[
    {ticket_id:'T1',plate_entry:'59-B1 123.45',status:'IN_PARKING'},
    {ticket_id:'T2',plate_entry:'30-AB 678.90',status:'IN_PARKING'}]},
    '/vehicle/exit':{result:{status:'COMPLETED',match_result:'MATCH'}}},{setTimeout(fn,ms){if(ms===250)lookup=fn;return 1;}});
  const zone=workflow(ui,'exit');ui.state.view='exit';await ui.RENDER.exit();
  choosePhoto(zone);ui.get('#exit-ticket').value='T1';ui.get('#exit-ticket').listeners.change();
  ui.get('#exit-plate').value='59-B1 123.45';ui.get('#exit-plate').listeners.input();
  assert.match(ui.get('#exit-match-note').textContent,/khớp vé/);
  await ui.get('#exit-submit').listeners.click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.get('#exit-match-note').textContent,'');
  assert.equal(ui.workflowDrafts.exit.ticketManual,false);
  choosePhoto(zone,'next-car.jpg');ui.get('#exit-plate').value='30-AB 678.90';ui.get('#exit-plate').listeners.input();
  await lookup();
  assert.equal(ui.get('#exit-ticket').value,'T2');
});

test('workflow shortcut requires a deliberate nonrepeated Ctrl or Command Enter', async () => {
  const ui=setup(); workflow(ui,'entry'); ui.state.view='entry'; await ui.RENDER.entry();
  let clicks=0; ui.get('#entry-submit').click=()=>clicks++;
  const key=ui.get('#entry-workflow').listeners.keydown;
  key({key:'Enter',preventDefault(){}});
  key({key:'Enter',ctrlKey:true,isComposing:true,preventDefault(){}});
  key({key:'Enter',ctrlKey:true,repeat:true,preventDefault(){}});
  assert.equal(clicks,0);
  key({key:'Enter',ctrlKey:true,preventDefault(){}});
  key({key:'Enter',metaKey:true,preventDefault(){}});
  assert.equal(clicks,2);
});

test('rapid log typing sends only the final query and navigation cancels pending search', async () => {
  const timers=new Map(); let seq=0;
  const ui=setup({'/logs?limit=50':{items:[],total:0}},{
    setTimeout(fn){const id=++seq;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},
  });
  ui.state.view='logs'; await ui.RENDER.logs();
  for(const value of ['3','30','30AB']){
    ui.get('#log-search').value=value; ui.get('#log-search').listeners.input();
  }
  assert.equal(timers.size,1); assert.equal(ui.requests.length,1);
  await [...timers.values()][0]();
  assert.equal(ui.requests.length,2);
  assert.match(ui.requests[1].url,/q=30AB$/);
  assert.equal(ui.logFilters.query,'30AB');
  ui.get('#log-search').value='next'; ui.get('#log-search').listeners.input();
  ui.previewCleanups.splice(0).forEach(fn=>fn());
  assert.equal(timers.size,0);
});

test('logs restore filters and one click clears search and status together', async () => {
  const ui=setup(); ui.state.view='logs';
  Object.assign(ui.logFilters,{query:'T1',status:'IN_PARKING',offset:500});
  await ui.RENDER.logs();
  assert.equal(ui.requests[0].url,'/logs?limit=50&offset=500&status=IN_PARKING&q=T1');
  assert.equal(ui.get('#log-search').value,'T1');
  assert.equal(ui.get('#log-filter').value,'IN_PARKING');
  await ui.get('#log-clear').listeners.click();
  assert.equal(ui.requests[1].url,'/logs?limit=50&offset=0');
  assert.equal(ui.logFilters.offset,0); assert.equal(ui.logFilters.query,'');
});

test('log pagination advances by one compact page and disables next at the last page', async () => {
  const ui=setup({
    '/logs?limit=50':{items:[{ticket_id:'FIRST'}],total:51},
    '/logs?limit=50&offset=50':{items:[{ticket_id:'LAST'}],total:51},
    '/logs?limit=50&offset=0':{items:[{ticket_id:'FIRST'}],total:51},
  });
  ui.state.view='logs'; await ui.RENDER.logs();
  assert.equal(ui.get('#log-prev').disabled,true);
  await ui.get('#log-next').listeners.click();
  assert.match(ui.get('#log-tbody').innerHTML,/LAST/);
  assert.equal(ui.get('#log-next').disabled,true);
  assert.equal(ui.get('#log-page').textContent,'Trang 2 / 2');
  await ui.get('#log-prev').listeners.click();
  assert.match(ui.get('#log-tbody').innerHTML,/FIRST/);
  assert.equal(ui.get('#log-prev').disabled,true);
});

test('login ignores a double click, communicates progress and permits retry after failure', async () => {
  let reject, calls=0;
  const ui=setup({}, {fetch:async()=>{calls++;return new Promise((resolve,r)=>{reject=r;});}});
  const btn=ui.get('#login-form button[type="submit"]'); btn.innerHTML='Đăng nhập';
  const pending=ui.doLogin({preventDefault(){}});
  await ui.doLogin({preventDefault(){}});
  assert.equal(calls,1); assert.equal(btn.disabled,true);
  assert.match(btn.innerHTML,/Đang đăng nhập/);
  reject(new Error('offline')); await pending;
  assert.equal(btn.disabled,false); assert.equal(btn.innerHTML,'Đăng nhập');
  assert.equal(ui.get('#login-error').hidden,false);
});

test('login motion control resumes a saved pause and stays in sync with dashboard control', () => {
  const stored = new Map([['its_reduce_motion','true']]), classes = new Set();
  const ui = setup({}, {
    localStorage: {getItem:k=>stored.get(k) ?? null,setItem:(k,v)=>stored.set(k,v)},
    window: {matchMedia:()=>({matches:false})},
  });
  ui.context.document.body={classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)}};
  for (const id of ['#motion-toggle','#login-motion-toggle']) {
    const node=ui.get(id); node.attributes={}; node.setAttribute=(k,v)=>node.attributes[k]=v;
  }
  vm.runInContext('initWinterEffects()',ui.context);
  assert.equal(classes.has('motion-paused'),true);
  assert.equal(ui.get('#login-motion-toggle').attributes['aria-label'],'Bật chuyển động');
  ui.get('#login-motion-toggle').listeners.click();
  assert.equal(classes.has('motion-paused'),false);
  assert.equal(stored.get('its_reduce_motion'),'false');
  assert.equal(ui.get('#motion-toggle').attributes['aria-pressed'],'false');
  ui.get('#motion-toggle').listeners.click();
  assert.equal(classes.has('motion-paused'),true);
  assert.equal(ui.get('#login-motion-toggle').attributes['aria-pressed'],'true');
});

test('Turbo changes the running 2D route speed without seeking, ignores repeat clicks and resets', () => {
  const timers = new Map(); let nextTimer=0;
  const ui=setup({}, {setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);}});
  const classes=new Set();
  ui.get('#login-view').classList={contains:k=>classes.has(k),toggle:(k,on)=>on?classes.add(k):classes.delete(k)};
  const animation={currentTime:45123,playbackRate:1,updatePlaybackRate(rate){this.playbackRate=rate;}};
  ui.get('.pixel-landscape').getAnimations=()=>[animation];
  vm.runInContext('initWinterEasterEggs()',ui.context);
  ui.get('#turbo-toggle').listeners.click();
  assert.equal(animation.playbackRate,3); assert.equal(animation.currentTime,45123);
  assert.equal(classes.has('winter-turbo'),true);
  assert.equal(ui.get('#turbo-toggle').attributes['aria-pressed'],'true');
  ui.get('#car-easter-hit').listeners.click(); assert.equal(timers.size,1);
  [...timers.values()][0].fn();
  assert.equal(animation.playbackRate,1); assert.equal(animation.currentTime,45123);
  assert.equal(classes.has('winter-turbo'),false);
  ui.state.motionPaused=true; ui.get('#turbo-toggle').listeners.click();
  assert.equal(animation.playbackRate,1);
  assert.match(ui.get('#winter-egg-status').textContent,/Bật chuyển động/);
  ui.state.motionPaused=false; ui.get('#turbo-toggle').listeners.click();
  vm.runInContext('clearWinterEggs()',ui.context);
  assert.equal(animation.playbackRate,1); assert.equal(classes.has('winter-turbo'),false);
});

test('review badge uses review KPI even when recent logs contain other tickets', async () => {
  const ui = setup({ '/operations/summary': { kpis: { review_tickets: 2 }, health: { code: 'NORMAL' } },
    '/logs?limit=6': { total: 50, items: [{ ticket_id: '<script>x</script>', status: 'COMPLETED' }] },
    '/tickets/active?limit=6': { items: [] } });
  await ui.RENDER.dashboard();
  assert.equal(ui.get('#review-badge').textContent, 2);
  assert.equal(ui.get('#review-badge').hidden, false);
  const html = ui.get('#view-content').innerHTML;
  assert.ok(html.includes('&lt;script&gt;x&lt;/script&gt;'));
  assert.equal((html.match(/<th>/g) || []).length, 5);
  assert.ok(!html.includes('AI Vision'));
});

test('dragged image is submitted, cleared, and its preview URL released', async () => {
  const ui = setup({ '/vehicle/entry': { result: { ticket_id: 'T1', plate_entry: '59-B1 069.99' } } });
  ui.state.view = 'entry';
  const zone = element();
  ui.get('#entry-drop').closest = () => zone;
  await ui.RENDER.entry();
  const image = new File(['image'], 'plate.png', { type: 'image/png' });
  zone.listeners.drop({ preventDefault() {}, dataTransfer: { files: [image] } });
  assert.ok(ui.get('#entry-preview').innerHTML.includes('blob:test-preview'));
  ui.get('#entry-plate').value='59-B1 069.99';
  await ui.get('#entry-submit').listeners.click();
  const sent = ui.requests.find(request => request.url === '/vehicle/entry');
  assert.equal(sent.options.body.get('file').name, 'plate.png');
  assert.equal(ui.get('#entry-preview').innerHTML, '');
  assert.equal(ui.get('#entry-submit').disabled, false);
  assert.deepEqual(ui.revoked, ['blob:test-preview']);
});

test('exit selection excludes tickets needing review', async () => {
  const ui = setup({ '/tickets/active': { items: [
    { ticket_id: 'ACTIVE-TICKET', plate_entry: '59-B1 069.99', status: 'IN_PARKING' },
    { ticket_id: 'REVIEW-TICKET', plate_entry: '59-B2 123.45', status: 'NEEDS_REVIEW' },
  ] } });
  ui.state.view = 'exit';
  ui.get('#exit-drop').closest = () => element();
  await ui.RENDER.exit();
  assert.ok(ui.get('#view-content').innerHTML.includes('ACTIVE-TICKET'));
  assert.ok(!ui.get('#view-content').innerHTML.includes('REVIEW-TICKET'));
});

test('log search matches exit plate as well as entry plate and ticket ID', async () => {
  const ui = setup({ '/logs?limit=50': { items: [], total:501 },
    '/logs?limit=50&offset=0&q=B2': {items:[{ticket_id:'OLD-T1', plate_exit:'59-B2 123.45'}], total:1},
    '/logs?limit=50&offset=0&q=nonexistent': {items:[], total:0} });
  ui.state.view = 'logs';
  await ui.RENDER.logs();
  ui.get('#log-search').value = 'B2';
  await ui.get('#log-search').listeners.keydown({key:'Enter',preventDefault(){}});
  assert.ok(ui.get('#log-tbody').innerHTML.includes('OLD-T1'));
  ui.get('#log-search').value = 'nonexistent';
  await ui.get('#log-search').listeners.keydown({key:'Enter',preventDefault(){}});
  assert.ok(!ui.get('#log-tbody').innerHTML.includes('T1'));
});

test('a late log search cannot replace the newer search results', async () => {
  const pending={};
  const ui=setup({}, {fetch:async url => {
    if(url==='/logs?limit=50') return {ok:true,json:async()=>({items:[],total:0})};
    return new Promise(resolve=>{pending[url]=items=>resolve({ok:true,json:async()=>({items,total:items.length})});});
  }});
  ui.state.view='logs'; await ui.RENDER.logs();
  ui.get('#log-search').value='old'; const older=ui.get('#log-search').listeners.keydown({key:'Enter',preventDefault(){}});
  ui.get('#log-search').value='new'; const newer=ui.get('#log-search').listeners.keydown({key:'Enter',preventDefault(){}});
  pending['/logs?limit=50&offset=0&q=new']([{ticket_id:'LATEST'}]); await newer;
  pending['/logs?limit=50&offset=0&q=old']([{ticket_id:'STALE'}]); await older;
  assert.ok(ui.get('#log-tbody').innerHTML.includes('LATEST'));
  assert.ok(!ui.get('#log-tbody').innerHTML.includes('STALE'));
});

test('review photos load with bearer authentication and release blob URLs on navigation', async () => {
  const requests=[];
  const ui=setup({}, {fetch:async(url,opts)=>{
    requests.push({url,opts}); return {ok:true,status:200,blob:async()=>new Blob(['image'],{type:'image/png'})};
  }});
  const nodes={};
  const details=element({open:true,dataset:{reviewPhotos:'T/a'},querySelector:sel=>nodes[sel] ||= element()});
  ui.lists['[data-review-photos]']=[details]; ui.state.token='fixture-token';
  vm.runInContext('bindReviewEvidence()',ui.context);
  details.listeners.toggle();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,2);
  assert.equal(requests[0].url,'/tickets/T%2Fa/images/entry');
  assert.equal(requests[0].opts.headers.Authorization,'Bearer fixture-token');
  assert.equal(nodes['[data-review-image="entry"]'].hidden,false);
  ui.previewCleanups.splice(0).forEach(fn=>fn());
  assert.equal(requests[0].opts.signal.aborted,true); assert.equal(ui.revoked.length,2);
});

for (const prefix of ['entry','exit']) {
  test(`a delayed ${prefix} response preserves a newly selected photo and plate`, async () => {
    let release;
    const ui=setup({}, {fetch:async url => {
      if (url.startsWith('/tickets/active')) return {ok:true,json:async()=>({items:[{ticket_id:'TA',status:'IN_PARKING'}]})};
      return new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({result:{ticket_id:'TA',status:'COMPLETED'}})});});
    }});
    ui.state.view=prefix;
    const zone=element(); ui.get(`#${prefix}-drop`).closest=()=>zone;
    await ui.RENDER[prefix]();
    ui.get('#exit-ticket').options=[{value:''},{value:'TA',remove(){}}]; ui.get('#exit-ticket').value='TA';
    const first=new File(['first'],'first.jpg',{type:'image/jpeg'});
    const next=new File(['next'],'next.jpg',{type:'image/jpeg'});
    zone.listeners.drop({preventDefault(){},dataTransfer:{files:[first]}});
    ui.get(`#${prefix}-plate`).value='30-AB 123.45';
    const request=ui.get(`#${prefix}-submit`).listeners.click();
    zone.listeners.drop({preventDefault(){},dataTransfer:{files:[next]}});
    ui.get(`#${prefix}-plate`).value='30-A8 123.45';
    release(); await request;
    assert.equal(ui.get(`#${prefix}-filename`).textContent,'next.jpg');
    assert.equal(ui.get(`#${prefix}-plate`).value,'30-A8 123.45');
    assert.equal(ui.get(`#${prefix}-meta`).hidden,false);
  });
}

for (const isActive of [true, false]) {
  test(`account active toggle sends ${!isActive} when current state is ${isActive}`, async () => {
    const ui = setup({ '/admin/users': { items: [{ username: 'operator', role: 'operator', is_active: isActive }] } });
    ui.state.view = 'admin';
    const btn = element({ dataset: { u: 'operator', op: 'active' } });
    ui.lists['[data-op]'] = [btn];
    await ui.RENDER.admin();
    await btn.listeners.click();
    const sent = ui.requests.find(request => request.url.endsWith('/active'));
    assert.equal(sent.options.body.get('is_active'), String(!isActive));
  });
}

test('pending action ignores a second click while its request is in progress', async () => {
  const ui = setup();
  const btn = element();
  let release, calls = 0;
  const action = () => { calls++; return new Promise(resolve => { release = resolve; }); };
  const first = ui.runPending(btn, 'Processing', action);
  await ui.runPending(btn, 'Processing', action);
  assert.equal(calls, 1);
  release(); await first;
  assert.equal(btn.disabled, false);
});

test('network failure produces an actionable message', async () => {
  const ui = setup({}, { fetch: async () => { throw new TypeError('Failed to fetch'); } });
  await assert.rejects(ui.api('/logs'), /Không kết nối được máy chủ/);
});

test('navigation abort preserves AbortError instead of showing connection failure', async () => {
  const error = new Error('aborted'); error.name = 'AbortError';
  const ui = setup({}, { fetch: async () => { throw error; } });
  await assert.rejects(ui.api('/logs'), ex => ex === error);
});

test('HTML returned with HTTP 200 is rejected before rendering', async () => {
  const ui = setup({}, { fetch: async () => ({ ok: true, json: async () => { throw new SyntaxError(); } }) });
  await assert.rejects(ui.api('/logs'), /dữ liệu không hợp lệ/);
});

test('provider error text reaches the user without being replaced by a TypeError', async () => {
  const ui = setup({}, { fetch: async () => ({ ok: false, json: async () => ({ error: { message: 'AI chưa cấu hình' } }) }) });
  await assert.rejects(ui.api('/ocr'), /AI chưa cấu hình/);
});

for (const [name, type, size] of [
  ['plate.gif', 'image/gif', 10], ['plate.bmp', 'image/bmp', 10],
  ['plate.png', 'text/plain', 10], ['plate.jpg', 'image/jpeg', 0],
  ['plate.jpg', 'image/jpeg', 10 * 1024 * 1024 + 1],
]) {
  test(`invalid upload rejected before preview: ${name}, ${type}, ${size} bytes`, async () => {
    const ui = setup();
    const zone = element(); ui.get('#entry-drop').closest = () => zone;
    const upload = ui.bindUpload('entry');
    zone.listeners.drop({ preventDefault() {}, dataTransfer: { files: [{ name, type, size }] } });
    assert.equal(upload.getFile(), null);
    assert.equal(ui.get('#entry-preview').innerHTML, '');
    assert.equal(ui.get('#toast').hidden, false);
  });
}

test('removing a selected image clears submission state and releases the preview', () => {
  const ui = setup(); const zone = element(); ui.get('#entry-drop').closest = () => zone;
  const upload = ui.bindUpload('entry');
  zone.listeners.drop({ preventDefault() {}, dataTransfer: { files: [new File(['data'], 'plate.webp', { type: 'image/webp' })] } });
  assert.ok(upload.getFile());
  ui.get('#entry-remove').listeners.click();
  assert.equal(upload.getFile(), null);
  assert.deepEqual(ui.revoked, ['blob:test-preview']);
});

test('viewer cannot submit an entry even if the handler is triggered directly', async () => {
  const ui = setup(); ui.state.user.role = 'viewer'; ui.state.view = 'entry';
  ui.get('#entry-drop').closest = () => element();
  await ui.RENDER.entry();
  await ui.get('#entry-submit').listeners.click();
  assert.ok(ui.get('#view-content').innerHTML.includes('disabled'));
  assert.equal(ui.requests.length, 0);
});

test('failed action restores the button so the user can retry', async () => {
  const ui = setup(); const btn = element({ innerHTML: 'Submit' });
  await ui.runPending(btn, 'Loading', async () => { throw new Error('Temporary failure'); });
  assert.equal(btn.disabled, false);
  assert.equal(btn.innerHTML, 'Submit');
  assert.equal(ui.get('#toast').textContent, 'Temporary failure');
});

function cameraFixture(prefix = 'entry', mediaOverride = {}) {
  const ui = setup();
  ui.get(`#${prefix}-drop`).closest = () => element();
  let stops = 0, requests = [], drawn = null;
  const track = { stop() { stops++; }, addEventListener() {}, getSettings() { return { deviceId: 'usb-1' }; } };
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
  const video = ui.get(`#${prefix}-camera-video`);
  Object.assign(video, { videoWidth: 3840, videoHeight: 2160, readyState: 4, play: async () => {}, pause() {} });
  const canvas = { getContext: () => ({ drawImage(...args) { drawn = args; } }),
    toBlob(callback) { callback(new Blob(['jpeg-frame'], { type: 'image/jpeg' })); } };
  ui.context.document.createElement = () => canvas;
  ui.context.File = File;
  ui.context.isSecureContext = true;
  ui.context.navigator = { mediaDevices: {
    getUserMedia: async constraints => { requests.push(constraints); return stream; },
    enumerateDevices: async () => [{ kind: 'videoinput', deviceId: 'usb-1', label: 'USB <camera>' }],
    ...mediaOverride,
  } };
  const upload = ui.bindUpload(prefix);
  return { ui, upload, video, canvas, stream, requests, get stops() { return stops; }, get drawn() { return drawn; } };
}

for (const prefix of ['entry', 'exit']) {
  test(`real camera ${prefix} capture becomes a JPEG upload and releases the device`, async () => {
    const fixture = cameraFixture(prefix), { ui, upload, canvas, video } = fixture;
    await ui.get(`#${prefix}-camera-open`).listeners.click();
    assert.equal(fixture.requests[0].audio, false);
    assert.equal(fixture.requests[0].video.facingMode.ideal, 'environment');
    assert.equal(video.srcObject, fixture.stream);
    assert.equal(ui.get(`#${prefix}-camera-shutter`).disabled, false);
    assert.match(ui.get(`#${prefix}-camera-devices`).innerHTML, /USB &lt;camera&gt;/);
    await ui.get(`#${prefix}-camera-shutter`).listeners.click();
    assert.equal(upload.getFile().type, 'image/jpeg');
    assert.match(upload.getFile().name, /^camera-.*\.jpg$/);
    assert.equal(canvas.width, 2560); assert.equal(canvas.height, 1440);
    assert.equal(fixture.drawn[0], video);
    assert.equal(fixture.stops, 1);
    assert.equal(video.srcObject, null);
    assert.equal(ui.get(`#${prefix}-camera-panel`).hidden, true);
    assert.equal(ui.requests.length, 0, 'capturing does not create a ticket or upload automatically');
  });
}

for (const action of ['close', 'navigate']) {
  test(`camera granted after ${action} is immediately released`, async () => {
    let grant;
    const fixture = cameraFixture('entry', { getUserMedia: () => new Promise(resolve => { grant = resolve; }) });
    const pending = fixture.ui.get('#entry-camera-open').listeners.click();
    if (action === 'close') fixture.ui.get('#entry-camera-close').listeners.click();
    else fixture.ui.previewCleanups.splice(0).forEach(cleanup => cleanup());
    grant(fixture.stream); await pending;
    assert.equal(fixture.stops, 1);
    assert.equal(fixture.video.srcObject, null);
    assert.equal(fixture.upload.getFile(), null);
    assert.equal(fixture.ui.get('#entry-camera-panel').hidden, true);
  });
}

test('switching camera releases the previous stream before requesting a device', async () => {
  const fixture = cameraFixture(), { ui } = fixture;
  await ui.get('#entry-camera-open').listeners.click();
  ui.get('#entry-camera-devices').value = 'rear-2';
  await ui.get('#entry-camera-devices').listeners.change();
  assert.equal(fixture.stops, 1);
  assert.equal(fixture.requests[1].video.deviceId.exact, 'rear-2');
  ui.previewCleanups.splice(0).forEach(cleanup => cleanup());
  assert.equal(fixture.stops, 2);
});

for (const [name, message] of [['NotAllowedError', 'quyền camera'], ['NotFoundError', 'Không tìm thấy camera'], ['NotReadableError', 'ứng dụng khác']]) {
  test(`camera reports actionable ${name} and allows retry`, async () => {
    const error = new Error('raw-device-error'); error.name = name;
    const fixture = cameraFixture('entry', { getUserMedia: async () => { throw error; } });
    await fixture.ui.get('#entry-camera-open').listeners.click();
    assert.match(fixture.ui.get('#entry-camera-message').textContent, new RegExp(message));
    assert.equal(fixture.ui.get('#entry-camera-shutter').disabled, true);
    assert.equal(fixture.ui.get('#entry-camera-open').disabled, false);
    assert.equal(fixture.video.srcObject, null);
  });
}

test('camera does not capture before the first frame arrives', async () => {
  const fixture = cameraFixture(), { ui, video } = fixture;
  video.readyState = 0; video.videoWidth = 0; video.videoHeight = 0;
  await ui.get('#entry-camera-open').listeners.click();
  await ui.get('#entry-camera-shutter').listeners.click();
  assert.equal(fixture.upload.getFile(), null);
  assert.equal(fixture.drawn, null);
  assert.match(ui.get('#entry-camera-message').textContent, /Chờ camera/);
});

test('failed frame encoding keeps the camera open and preserves the error', async () => {
  const fixture = cameraFixture(), { ui, canvas } = fixture;
  canvas.toBlob = callback => callback(null);
  await ui.get('#entry-camera-open').listeners.click();
  await ui.get('#entry-camera-shutter').listeners.click();
  assert.equal(fixture.upload.getFile(), null);
  assert.equal(ui.get('#entry-camera-panel').hidden, false);
  assert.equal(ui.get('#entry-camera-shutter').disabled, false);
  assert.match(ui.get('#entry-camera-message').textContent, /chưa tạo được ảnh/);
});

test('closing camera while encoding prevents a late photo replacing the selected file', async () => {
  const fixture = cameraFixture(), { ui, canvas } = fixture;
  let encoded;
  canvas.toBlob = callback => { encoded = callback; };
  await ui.get('#entry-camera-open').listeners.click();
  const pending = ui.get('#entry-camera-shutter').listeners.click();
  ui.get('#entry-camera-close').listeners.click();
  encoded(new Blob(['late-frame'], { type: 'image/jpeg' })); await pending;
  assert.equal(fixture.upload.getFile(), null);
  assert.equal(fixture.stops, 1);
});

test('scan only calls OCR, escapes plate text, and asks for image comparison', async () => {
  const ui = setup({ '/ocr': { ocr: { text: '<plate>59-B1 069.99' } } });
  const zone = element(); ui.get('#entry-drop').closest = () => zone;
  ui.bindUpload('entry');
  zone.listeners.drop({ preventDefault() {}, dataTransfer: { files: [new File(['image'], 'plate.jpg', { type: 'image/jpeg' })] } });
  await ui.get('#entry-scan').listeners.click();
  assert.equal(ui.requests.length, 1); assert.equal(ui.requests[0].url, '/ocr');
  assert.match(ui.get('#entry-scan-result').innerHTML, /&lt;plate&gt;/);
  assert.match(ui.get('#entry-scan-result').innerHTML, /OCR chưa chắc chắn/);
  assert.doesNotMatch(ui.get('#entry-scan-result').innerHTML, /id="entry-use-scan"/);
  assert.equal(ui.get('#entry-scan').disabled, false);
});

test('OCR for a replaced photo is aborted and cannot overwrite the newer photo result', async () => {
  const ui = setup(); let resolve;
  const zone = element(); ui.get('#entry-drop').closest = () => zone;
  ui.bindUpload('entry');
  const drop = name => zone.listeners.drop({ preventDefault() {}, dataTransfer: { files: [new File(['image'], name, { type: 'image/jpeg' })] } });
  drop('first.jpg');
  let signal;
  ui.context.fetch = (_, options) => { signal = options.signal; return new Promise(done => { resolve = done; }); };
  const pending = ui.get('#entry-scan').listeners.click();
  drop('second.jpg');
  assert.equal(signal.aborted, true);
  resolve({ ok: true, json: async () => ({ ocr: { text: 'OLD PLATE' } }) }); await pending;
  assert.equal(ui.get('#entry-scan-result').hidden, true);
  assert.equal(ui.get('#entry-scan-result').innerHTML, '');
  assert.equal(ui.get('#entry-scan').disabled, false);
});

const expiredResponse = () => ({ ok: false, status: 401, json: async () => ({ detail: 'Unauthorized' }) });
const submitEvent = { preventDefault() {} };

test('expired session stops camera and preserves the selected photo and manual plate', async () => {
  const fixture = cameraFixture(), { ui, upload } = fixture;
  const file = new File(['image'], 'plate.jpg', { type: 'image/jpeg' });
  ui.get('#entry-camera-native').files = [file]; ui.get('#entry-camera-native').listeners.change();
  ui.get('#entry-plate').value = '59-B1 069.99';
  await ui.get('#entry-camera-open').listeners.click();
  ui.state.token = 'expired'; ui.context.fetch = async () => expiredResponse();
  await assert.rejects(ui.api('/ocr', { method: 'POST' }), /Phiên đăng nhập đã hết hạn/);
  assert.equal(ui.state.sessionExpired, true); assert.equal(ui.state.token, '');
  assert.equal(ui.get('#session-dialog').open, true);
  assert.equal(ui.get('#session-password').focused, true);
  assert.equal(upload.getFile(), file);
  assert.equal(ui.get('#entry-preview').hidden, false);
  assert.equal(ui.get('#entry-plate').value, '59-B1 069.99');
  assert.equal(fixture.stops, 1); assert.deepEqual(ui.revoked, []);
});

test('reauthentication retains the photo and does not automatically repeat a ticket write', async () => {
  const fixture = cameraFixture(), { ui, upload } = fixture;
  const file = new File(['image'], 'plate.jpg', { type: 'image/jpeg' });
  ui.get('#entry-camera-native').files = [file]; ui.get('#entry-camera-native').listeners.change();
  const requests = [];
  ui.context.fetch = async url => {
    requests.push(url);
    return url === '/auth/login' ? { ok: true, json: async () => ({ access_token: 'fresh-token', user: { username: 'admin', role: 'admin' } }) } : expiredResponse();
  };
  ui.state.view = 'entry'; ui.state.token = 'expired';
  await assert.rejects(ui.api('/vehicle/entry', { method: 'POST' }));
  ui.get('#session-password').value = 'example-password';
  await ui.doSessionLogin(submitEvent);
  assert.deepEqual(requests, ['/vehicle/entry', '/auth/login']);
  assert.equal(ui.state.token, 'fresh-token'); assert.equal(ui.state.sessionExpired, false);
  assert.equal(ui.get('#session-dialog').open, false);
  assert.equal(ui.get('#session-password').value, '');
  assert.equal(upload.getFile(), file);
});

test('incorrect reauthentication password keeps the dialog open and clears the password', async () => {
  const ui = setup({}, { fetch: async () => expiredResponse() });
  ui.requestReauthentication(); ui.get('#session-password').value = 'wrong-password';
  await ui.doSessionLogin(submitEvent);
  assert.equal(ui.state.sessionExpired, true); assert.equal(ui.state.token, '');
  assert.equal(ui.get('#session-dialog').open, true);
  assert.match(ui.get('#session-error').textContent, /mật khẩu không đúng/);
  assert.equal(ui.get('#session-password').value, '');
  assert.equal(ui.get('#session-submit').disabled, false);
});

test('permission denial does not expire an otherwise valid login', async () => {
  const ui = setup({}, { fetch: async () => ({ ok: false, status: 403, json: async () => ({ detail: 'Forbidden' }) }) });
  ui.state.token = 'valid-token';
  await assert.rejects(ui.api('/admin/users'), /Forbidden/);
  assert.equal(ui.state.token, 'valid-token'); assert.equal(ui.state.sessionExpired, false);
  assert.notEqual(ui.get('#session-dialog').open, true);
});

test('simultaneous expired requests open one reauthentication dialog', async () => {
  const ui = setup(); const replies = [];
  ui.state.token = 'expired';
  ui.context.fetch = () => new Promise(resolve => replies.push(resolve));
  const first = ui.api('/logs').catch(error => error), second = ui.api('/tickets/active').catch(error => error);
  replies[0](expiredResponse()); replies[1](expiredResponse()); await Promise.all([first, second]);
  assert.equal(ui.get('#session-dialog').modalCount, 1);
});

test('late unauthorized response from an old token cannot invalidate the refreshed session', async () => {
  const ui = setup(); let finish;
  ui.state.token = 'old-token';
  ui.context.fetch = () => new Promise(resolve => { finish = resolve; });
  const pending = ui.api('/logs').catch(error => error);
  ui.requestReauthentication();
  ui.context.fetch = async () => ({ ok: true, json: async () => ({ access_token: 'new-token', user: { username: 'admin', role: 'admin' } }) });
  await ui.doSessionLogin(submitEvent);
  finish(expiredResponse()); await pending;
  assert.equal(ui.state.token, 'new-token'); assert.equal(ui.state.sessionExpired, false);
  assert.equal(ui.get('#session-dialog').open, false);
});

test('reauthentication applies a downgraded role without permitting a ticket write', async () => {
  const ui = setup({ '/auth/login': { access_token: 'viewer-token', user: { username: 'admin', role: 'viewer' } } });
  ui.requestReauthentication(); await ui.doSessionLogin(submitEvent);
  assert.equal(ui.get('#nav-admin').hidden, true);
  assert.equal(ui.get('#entry-submit').disabled, true);
  assert.equal(ui.get('#exit-submit').disabled, true);
});

test('login failure before an authenticated user exists does not open recovery dialog', async () => {
  const ui = setup({}, { fetch: async () => expiredResponse() }); ui.state.user = null;
  await assert.rejects(ui.api('/auth/me'), /Phiên đăng nhập/);
  assert.notEqual(ui.get('#session-dialog').open, true);
  await assert.rejects(ui.api('/auth/login', { method: 'POST' }), /mật khẩu không đúng/);
});

