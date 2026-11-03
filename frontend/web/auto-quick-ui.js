'use strict';
let quickQRGeneration=0,quickQRController=null,quickQRFocus=null,quickQRPoll=null,quickQRKey=null;
function quickRequestKey(){
  if(globalThis.crypto?.randomUUID)return crypto.randomUUID();
  if(!globalThis.crypto?.getRandomValues)throw new Error('Trình duyệt chưa hỗ trợ tạo mã an toàn.');
  const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
  return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
}
function closeQuickPaymentQR(){
  quickQRPoll?.dispose();
  quickQRGeneration++;quickQRController?.abort();quickQRPoll?.clear();
  if($('#quick-qr-dialog').open)$('#quick-qr-dialog').close();
  document.body?.classList.remove('printing-quick-receipt');quickQRFocus?.focus();
}
function openQuickPaymentQR(code=null){
  if(code!=null && typeof code!=='string')code=null;
  if(!code&&!canWrite())return;
  quickQRGeneration++;quickQRController?.abort();quickQRPoll?.clear();
  quickQRPoll?.dispose();quickQRPoll=createVisibilityPoller();
  quickQRFocus=document.activeElement;quickQRKey=code?null:quickRequestKey();
  $('#quick-qr-title').textContent=code?'Yêu cầu QR thanh toán':'Tạo mã QR thanh toán';
  $('#quick-qr-guidance').hidden=!!code;
  $('#quick-qr-amount').value='';$('#quick-qr-amount').disabled=false;
  $('#quick-qr-form').hidden=!!code;$('#quick-qr-result').innerHTML='';$('#quick-qr-error').hidden=true;
  $('#quick-qr-submit').disabled=false;$('#quick-qr-submit').textContent='Tạo mã QR';
  if(!$('#quick-qr-dialog').open)$('#quick-qr-dialog').showModal();
  if(code)refreshQuickPaymentQR(code,quickQRGeneration);else $('#quick-qr-amount').focus();
}
function paintQuickPaymentQR(qr,monitor,generation){
  if(generation!==quickQRGeneration||!$('#quick-qr-dialog').open)return;
  quickQRPoll?.clear();$('#quick-qr-form').hidden=true;
  $('#quick-qr-error').hidden=true;$('#quick-qr-error').textContent='';
  const pending=qr.status==='pending',paid=qr.status==='paid';
  $('#quick-qr-title').textContent=paid?'Phiếu thu MB':pending?'QR thanh toán MB':'Yêu cầu QR thanh toán';
  $('#quick-qr-guidance').hidden=!pending;
  const status={pending:'Đang chờ tiền vào MB',paid:'Đã thanh toán · MB đã đối soát',expired:'Mã đã hết hạn',cancelled:'Yêu cầu đã dừng'}[qr.status]||'Cần kiểm tra';
  $('#quick-qr-result').innerHTML=`<p role="status">${badge(status,paid?'success':pending?'warning':'neutral')}</p>
    <div class="quick-qr-layout">${pending?`<img class="mb-transfer-qr" src="${esc(qr.qr_image)}" alt="QR thanh toán MB ${esc(money(qr.amount))}" />`:`<div><h3>${paid?'Phiếu thu MB':'Yêu cầu thanh toán'}</h3><strong class="ticket-amount">${money(qr.amount)}</strong></div>`}
    <dl class="ticket-facts"><div><dt>Nội dung</dt><dd class="mb-code">${esc(qr.code)}</dd></div><div><dt>Người nhận</dt><dd>${esc(qr.account_name)}</dd></div><div><dt>Tài khoản</dt><dd>${esc(qr.account_no)}</dd></div><div><dt>Số tiền</dt><dd>${money(qr.amount)}</dd></div>
      ${paid?`<div><dt>Phiếu thu</dt><dd>${esc(qr.receipt_id)}</dd></div><div><dt>Giao dịch MB</dt><dd>${esc(qr.bank_reference)}</dd></div><div><dt>Ghi nhận lúc</dt><dd>${formatTime(qr.paid_at)}</dd></div>`:`<div><dt>Hạn mã</dt><dd>${formatTime(qr.expires_at)}</dd></div>`}</dl></div>
    <p class="ticket-note" id="quick-auto-message">${pending?esc(mbMonitorMessage(monitor)):paid?'Phiếu thu đã được lưu tự động từ giao dịch MB khớp.':'Nếu khách đã chuyển, kiểm tra giao dịch trước khi tạo mã khác.'}</p>
    <div class="row-actions no-print">${pending?`<a class="btn btn-soft" href="${esc(qr.qr_image)}" download="QR-${esc(qr.code)}.png">Tải mã QR</a>`:''}
      ${paid?'<button class="btn btn-soft" id="quick-receipt-print" type="button">In phiếu thu</button>':''}
      <button class="btn btn-soft" id="quick-qr-refresh" type="button">Cập nhật trạng thái</button>
      ${canWrite()?'<button class="btn btn-soft" id="quick-qr-new" type="button">Tạo mã khác</button>':''}
      ${pending&&canWrite()?'<button class="btn btn-soft" id="quick-qr-cancel" type="button">Dừng mã</button>':''}</div>`;
  $('#quick-qr-refresh')?.addEventListener('click',()=>refreshQuickPaymentQR(qr.code,generation));
  $('#quick-qr-new')?.addEventListener('click',()=>openQuickPaymentQR());
  $('#quick-receipt-print')?.addEventListener('click',()=>{document.body.classList.add('printing-quick-receipt');window.print();});
  $('#quick-qr-cancel')?.addEventListener('click',async()=>{
    try{const data=await api('/payments/qr-requests/'+encodeURIComponent(qr.code)+'/cancel',{method:'POST'});paintQuickPaymentQR(data.qr,null,generation);}
    catch(error){if(generation===quickQRGeneration){$('#quick-qr-error').textContent=error.message;$('#quick-qr-error').hidden=false;}}
  });
  if(pending)quickQRPoll?.schedule(()=>refreshQuickPaymentQR(qr.code,generation),1000);
}
async function refreshQuickPaymentQR(code,generation){
  if(generation!==quickQRGeneration||!$('#quick-qr-dialog').open)return;
  quickQRPoll?.clear();
  try{
    quickQRController?.abort();quickQRController=new AbortController();
    const data=await api('/payments/qr-requests/'+encodeURIComponent(code),{signal:quickQRController.signal});
    paintQuickPaymentQR(data.qr,data.monitor,generation);
  }catch(error){
    if(generation!==quickQRGeneration||error.name==='AbortError')return;
    $('#quick-qr-error').textContent=error.message;$('#quick-qr-error').hidden=false;
    quickQRPoll?.schedule(()=>refreshQuickPaymentQR(code,generation),5000);
  }
}
function initQuickPaymentQR(){
  $('#quick-qr-close').addEventListener('click',closeQuickPaymentQR);
  $('#quick-qr-dialog').addEventListener('cancel',()=>{quickQRPoll?.dispose();quickQRGeneration++;quickQRController?.abort();quickQRPoll?.clear();});
  $('#quick-qr-amount').addEventListener('input',()=>{
    quickQRGeneration++;quickQRController?.abort();quickQRPoll?.clear();quickQRKey=quickRequestKey();
    $('#quick-qr-result').innerHTML='';$('#quick-qr-error').hidden=true;$('#quick-qr-submit').disabled=false;$('#quick-qr-submit').textContent='Tạo mã QR';
  });
  $('#quick-qr-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('#quick-qr-submit'),amount=Number($('#quick-qr-amount').value);
    if(button.disabled||!canWrite())return;
    if(!Number.isSafeInteger(amount)||amount<1||amount>1000000000){$('#quick-qr-error').textContent='Nhập số tiền nguyên từ 1 đến 1 tỷ đồng.';$('#quick-qr-error').hidden=false;return;}
    const generation=++quickQRGeneration;quickQRController?.abort();quickQRController=new AbortController();
    button.disabled=true;button.textContent='Đang tạo QR tự động…';$('#quick-qr-error').hidden=true;
    try{
      const data=await api('/payments/qr-requests',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({amount,idempotency_key:quickQRKey}),signal:quickQRController.signal});
      paintQuickPaymentQR(data.qr,data.monitor,generation);
    }catch(error){if(generation===quickQRGeneration&&error.name!=='AbortError'){$('#quick-qr-error').textContent=error.message;$('#quick-qr-error').hidden=false;}}
    finally{if(generation===quickQRGeneration){button.disabled=false;button.textContent='Tạo mã QR';}}
  });
  globalThis.addEventListener?.('afterprint',()=>document.body.classList.remove('printing-quick-receipt'));
}
