'use strict';

function money(value) { return value == null ? 'Chưa có biểu phí' : new Intl.NumberFormat('vi-VN', {style:'currency',currency:'VND',maximumFractionDigits:0}).format(value); }
function vehicleLabel(value) { return {motorcycle:'Xe máy',car:'Ô tô'}[value] || 'Vé cũ'; }
function ticketAction(id,label='Vé QR / thu phí') { return `<button type="button" class="btn btn-soft ticket-action" data-ticket-pass="${esc(id)}">${esc(label)}</button>`; }

async function renderPayments(){
  const version=state.viewVersion;
  $('#view-content').innerHTML=`<section class="card payments-page">
    <div class="card-heading"><h3>Thanh toán &amp; phiếu thu</h3><div class="row-actions">${canWrite()?'<button type="button" class="btn btn-primary" id="payments-create-qr">Tạo QR thanh toán</button>':''}<span class="count-chip" id="payments-count">Đang tải…</span></div></div>
    <p class="pricing-intro">Chọn vé đã xác nhận xe ra để thu tiền hoặc xem lại phiếu thu.</p>
    ${canWrite()?'<p class="ticket-note">QR nhập số tiền và QR theo vé hỗ trợ tự đối soát khi kết nối MB sẵn sàng.</p>':''}
    <div id="payments-notices"></div>
    <div class="form-row payments-filters"><label>Trạng thái phí<select id="payments-filter"><option value="">Tất cả</option><option value="unpaid">Chưa thu tiền</option><option value="paid">Đã thu tiền</option><option value="unconfigured">Chưa có biểu phí</option></select></label>
      <label>Tìm vé<input id="payments-search" type="search" maxlength="100" placeholder="Biển số hoặc mã vé" /></label>
      ${canWrite()?'<button type="button" class="btn btn-soft" id="payments-entry">Ghi nhận xe vào</button>':''}</div>
    <div class="table-wrap log-table" tabindex="0" role="region" aria-label="Danh sách thanh toán"><table><thead><tr><th>Vé / biển số</th><th>Giờ ra</th><th>Trạng thái phí</th><th>Số tiền</th><th>Hình thức thu</th><th>Thao tác</th></tr></thead><tbody id="payments-body"></tbody></table></div>
    <div class="log-pagination"><button class="btn btn-soft" id="payments-prev" type="button" disabled>Trang trước</button><span id="payments-page" role="status"></span><button class="btn btn-soft" id="payments-next" type="button" disabled>Trang sau</button></div>
    <section class="quick-history"><h3>Lịch sử QR nhập số tiền</h3><p id="quick-monitor-status" class="ticket-note" role="status">Đang kiểm tra trạng thái MB…</p>
      <div class="form-row payments-filters"><label>Trạng thái QR<select id="quick-history-filter"><option value="">Tất cả</option><option value="pending">Chờ MB</option><option value="paid">Đã thanh toán</option><option value="expired">Hết hạn</option><option value="cancelled">Đã dừng</option></select></label>
        <label>Tìm yêu cầu QR<input id="quick-history-search" type="search" maxlength="100" placeholder="Nội dung chuyển khoản hoặc mã phiếu thu" /></label></div>
      <p id="quick-history-error" role="alert" hidden></p><button class="btn btn-soft" id="quick-history-retry" type="button" hidden>Thử tải lại lịch sử QR</button>
      <div class="table-wrap" tabindex="0" role="region" aria-label="Lịch sử QR nhập số tiền"><table><thead><tr><th>Nội dung</th><th>Số tiền</th><th>Trạng thái</th><th>Tạo lúc</th><th>Thao tác</th></tr></thead><tbody id="quick-history-body"></tbody></table></div>
      <div class="log-pagination"><button class="btn btn-soft" id="quick-history-prev" type="button" disabled>QR trước</button><span id="quick-history-page" role="status"></span><button class="btn btn-soft" id="quick-history-next" type="button" disabled>QR sau</button></div></section>
  </section>`;
  let disposed=false,request=0,controller,timer,offset=0,total=0,historyTimer,historyController;
  const historyPoll=createVisibilityPoller();
  let historyOffset=0,historyTarget=0,historyTotal=0,historyRequest=0,historyDebounce;
  const alive=()=>!disposed&&state.view==='payments'&&state.viewVersion===version;
  function notices(config){
    const enabled=(config.tariffs||[]).filter(t=>t.enabled).map(t=>vehicleLabel(t.vehicle_type));
    const admin=state.user?.role==='admin';
    $('#payments-notices').innerHTML=`<div class="payment-setup">
      <p><strong>${enabled.length?'Đang tính phí: '+esc(enabled.join(', ')):'Tính phí gửi xe chưa được bật.'}</strong> ${enabled.length?'Giá đã lưu trên từng vé được giữ nguyên.':'Mở Biểu phí, chỉnh mức tiền rồi kích hoạt để áp dụng cho vé mới.'}</p>
      <p>Vé tạo trước khi bật biểu phí không tự bị tính phí hồi tố.</p>
      <p>${config.mb_enabled?'Chuyển khoản MB đã được kích hoạt.':config.receiver_saved?'Tài khoản MB mặc định đã lưu, nhưng chuyển khoản MB chưa được kích hoạt.':'Chuyển khoản MB chưa được thiết lập.'} ${!admin&&!enabled.length?'Nhờ quản trị viên cấu hình biểu phí trước khi thu.':''}</p>
      ${admin?`<div class="row-actions"><button class="btn btn-soft" type="button" id="payments-pricing">Mở biểu phí</button><button class="btn btn-soft" type="button" id="payments-bank">Mở kết nối MB</button></div>`:''}
    </div>`;
    $('#payments-pricing')?.addEventListener('click',()=>showView('pricing'));
    $('#payments-bank')?.addEventListener('click',()=>showView('mb'));
  }
  function rows(items){
    const labels={paid:['Đã thu tiền','success'],unpaid:['Chưa thu tiền','warning'],unconfigured:['Chưa có biểu phí','neutral'],needs_review:['Cần kiểm tra','danger']};
    const methods={cash:'Tiền mặt',transfer:'Chuyển khoản · thủ công',mb_transfer:'MB · đã đối soát'};
    $('#payments-body').innerHTML=items.map(item=>{
      const [label,tone]=labels[item.payment_state]||['Cần kiểm tra','warning'];
      const action=item.payment_state==='paid'?'Xem phiếu thu':item.payment_state==='unpaid'&&canWrite()?'Thanh toán':'Mở vé';
      return `<tr><td><strong class="plate">${esc(item.plate_entry||'—')}</strong><small class="payment-ticket-id">${esc(item.ticket_id)}</small></td><td class="time-cell">${formatTime(item.exit_time)}</td><td>${badge(label,tone)}</td><td>${item.amount==null?'—':money(item.amount)}</td><td>${esc(methods[item.method]||'—')}</td><td>${ticketAction(item.ticket_id,action)}</td></tr>`;
    }).join('')||`<tr><td colspan="6">${emptyState('search','Chưa có vé phù hợp','Vé đã xác nhận xe ra sẽ xuất hiện ở đây. Bạn có thể đổi bộ lọc hoặc tìm mã vé khác.')}</td></tr>`;
  }
  function pagination(){
    $('#payments-prev').disabled=offset===0;
    $('#payments-next').disabled=offset+50>=total;
    $('#payments-page').textContent=`Trang ${Math.floor(offset/50)+1} / ${Math.max(1,Math.ceil(total/50))}`;
  }
  async function load(nextOffset=0){
    clearTimeout(timer);controller?.abort();controller=new AbortController();const current=++request;
    const params=new URLSearchParams({limit:'50',offset:String(nextOffset)});
    if($('#payments-filter').value)params.set('payment_state',$('#payments-filter').value);
    if($('#payments-search').value.trim())params.set('q',$('#payments-search').value.trim());
    $('#payments-prev').disabled=$('#payments-next').disabled=true;
    $('#payments-page').textContent='Đang tải…';
    $('#payments-body').innerHTML='<tr><td colspan="6">Đang tải danh sách thanh toán…</td></tr>';
    try{
      const data=await api('/payments?'+params,{signal:controller.signal});
      if(!alive()||current!==request)return;
      offset=nextOffset;total=data.total||0;
      notices(data.configuration||{});rows(data.items||[]);
      $('#payments-count').textContent=`${(data.items||[]).length} / ${total} vé`;
      pagination();
    }catch(error){
      if(!alive()||current!==request||error.name==='AbortError')return;
      $('#payments-page').textContent='Chưa tải được dữ liệu';
      $('#payments-body').innerHTML=`<tr><td colspan="6"><p role="alert">${esc(error.message)}</p><button class="btn btn-soft" id="payments-retry" type="button">Thử lại</button></td></tr>`;
      $('#payments-retry').addEventListener('click',()=>load(nextOffset));
    }
  }
  $('#payments-entry')?.addEventListener('click',()=>showView('entry'));
  $('#payments-create-qr')?.addEventListener('click',()=>openQuickPaymentQR());
  $('#payments-filter').addEventListener('change',()=>load(0));
  $('#payments-search').addEventListener('input',()=>{
    clearTimeout(timer);controller?.abort();request++;
    $('#payments-prev').disabled=$('#payments-next').disabled=true;
    timer=setTimeout(()=>load(0),250);
  });
  $('#payments-search').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();return load(0);}});
  $('#payments-prev').addEventListener('click',()=>load(Math.max(0,offset-50)));
  $('#payments-next').addEventListener('click',()=>load(offset+50));
  async function history(nextOffset=historyOffset,background=false){
    if(!alive())return;
    let pollDelay=5000;
    historyTarget=nextOffset;
    historyPoll.clear();clearTimeout(historyDebounce);
    historyController?.abort();historyController=new AbortController();const current=++historyRequest;
    const params=new URLSearchParams({limit:'25',offset:String(nextOffset)});
    if($('#quick-history-filter').value)params.set('status',$('#quick-history-filter').value);
    if($('#quick-history-search').value.trim())params.set('q',$('#quick-history-search').value.trim());
    $('#quick-history-prev').disabled=$('#quick-history-next').disabled=true;
    $('#quick-history-error').hidden=$('#quick-history-retry').hidden=true;
    if(!background){
      $('#quick-history-page').textContent='Đang tải…';
      $('#quick-history-body').innerHTML='<tr><td colspan="5">Đang tải lịch sử QR…</td></tr>';
    }
    try{
      const data=await api('/payments/qr-requests?'+params,{signal:historyController.signal});
      if(!alive()||current!==historyRequest)return;
      if((data.items||[]).some(row=>row.status==='pending'))pollDelay=2000;
      historyTotal=data.total||0;
      if(nextOffset>0&&nextOffset>=historyTotal)return await history(Math.max(0,Math.ceil(historyTotal/25)-1)*25);
      historyOffset=nextOffset;
      $('#quick-monitor-status').textContent=mbMonitorMessage(data.monitor);
      const states={pending:['Chờ MB','warning'],paid:['Đã thanh toán','success'],expired:['Hết hạn','neutral'],cancelled:['Đã dừng','neutral']};
      const historyHTML=(data.items||[]).map(row=>{
        const [label,tone]=states[row.status]||['Cần kiểm tra','neutral'];
        return `<tr><td class="ticket-id">${esc(row.code)}</td><td>${money(row.amount)}</td><td>${badge(label,tone)}</td><td>${formatTime(row.created_at)}</td><td><button type="button" class="btn btn-soft" data-quick-payment="${esc(row.code)}">${row.status==='paid'?'Xem phiếu thu':row.status==='pending'?'Mở QR':'Xem yêu cầu'}</button></td></tr>`;
      }).join('')||'<tr><td colspan="5">Không có yêu cầu QR phù hợp. Thử đổi trạng thái hoặc từ khóa tìm kiếm.</td></tr>';
      if($('#quick-history-body').innerHTML!==historyHTML)$('#quick-history-body').innerHTML=historyHTML;
      $('#quick-history-page').textContent=`Trang ${Math.floor(historyOffset/25)+1} / ${Math.max(1,Math.ceil(historyTotal/25))} · ${historyTotal} yêu cầu`;
      $('#quick-history-prev').disabled=historyOffset===0;
      $('#quick-history-next').disabled=historyOffset+25>=historyTotal;
    }catch(error){
      if(!alive()||current!==historyRequest||error.name==='AbortError')return;
      $('#quick-monitor-status').textContent='Chưa cập nhật được trạng thái MB. Dữ liệu hiển thị có thể đã cũ.';
      $('#quick-history-error').textContent=error.message;
      $('#quick-history-error').hidden=$('#quick-history-retry').hidden=false;
      $('#quick-history-page').textContent='Chưa tải được lịch sử QR';
      if(!background)$('#quick-history-body').innerHTML='<tr><td colspan="5">Chưa tải được dữ liệu. Thử tải lại lịch sử QR.</td></tr>';
    }finally{if(alive()&&current===historyRequest)historyPoll.schedule(()=>history(nextOffset,true),pollDelay);}
  }
  $('#quick-history-filter').addEventListener('change',()=>history(0));
  $('#quick-history-search').addEventListener('input',()=>{
    historyPoll.clear();clearTimeout(historyDebounce);historyController?.abort();historyRequest++;
    $('#quick-history-prev').disabled=$('#quick-history-next').disabled=true;
    historyDebounce=setTimeout(()=>history(0),250);
  });
  $('#quick-history-search').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();return history(0);}});
  $('#quick-history-prev').addEventListener('click',()=>history(Math.max(0,historyOffset-25)));
  $('#quick-history-next').addEventListener('click',()=>history(historyOffset+25));
  $('#quick-history-retry').addEventListener('click',()=>history(historyTarget));
  previewCleanups.push(()=>{disposed=true;historyPoll.dispose();clearTimeout(timer);historyPoll.clear();clearTimeout(historyDebounce);controller?.abort();historyController?.abort();});
  await load(0);
  if(alive())await history();
}

let ticketPassGeneration=0, ticketPassController=null, ticketPassData=null, ticketPassReturnFocus=null;
function closeTicketPass() {
  stopMBTransfer();
  ticketPassGeneration++; ticketPassController?.abort(); ticketPassData=null;
  const dialog=$('#ticket-dialog');
  if (dialog.open) dialog.close();
  document.body?.classList.remove('printing-ticket');
  ticketPassReturnFocus?.focus();
}
async function openTicketPass(id) {
  stopMBTransfer();
  const dialog=$('#ticket-dialog'), content=$('#ticket-dialog-content');
  dialog.dataset.paymentMode='';
  if (!dialog.open) { ticketPassReturnFocus=document.activeElement; dialog.showModal(); }
  const generation=++ticketPassGeneration;
  ticketPassController?.abort(); ticketPassController=new AbortController();
  content.innerHTML='<p role="status">Đang tải vé và thông tin thu phí…</p>';
  try {
    const data=await api('/tickets/'+encodeURIComponent(id)+'/pass',{signal:ticketPassController.signal});
    if (generation!==ticketPassGeneration || !dialog.open) return;
    ticketPassData=data;
    const t=data.ticket, f=data.finance, receipt=f.receipt;
    const label={paid:'Đã thu tiền',unpaid:'Chưa thu tiền',estimate:'Tạm tính',unconfigured:'Chưa áp dụng phí',cancelled:'Đã hủy'}[f.state];
    const receiptHTML=receipt ? `<dl class="ticket-facts"><div><dt>Số phiếu thu</dt><dd>${esc(receipt.receipt_id)}</dd></div><div><dt>Hình thức</dt><dd>${receipt.method==='cash'?'Tiền mặt':receipt.verification==='mb_verified'?'MB · đã đối soát':'Chuyển khoản · xác nhận thủ công'}</dd></div>${receipt.bank_reference?`<div><dt>Mã giao dịch MB</dt><dd>${esc(receipt.bank_reference)}</dd></div>`:''}<div><dt>Khách đưa</dt><dd>${money(receipt.received_amount)}</dd></div><div><dt>Tiền thừa</dt><dd>${money(receipt.change_amount)}</dd></div><div><dt>Người thu</dt><dd>${esc(receipt.paid_by)}</dd></div><div><dt>Lúc thu</dt><dd>${formatTime(receipt.paid_at)}</dd></div></dl>` : '';
    content.innerHTML=`<div class="ticket-layout"><section class="ticket-pass">
      <h3>ITS Parking · Vé gửi xe</h3><p class="ticket-plate">${esc(t.plate_entry || 'Chưa rõ biển số')}</p>
      <img class="ticket-qr-image" src="${esc(data.qr_image)}" alt="Mã QR của vé ${esc(t.ticket_id)}" />
      <p class="ticket-code">${esc(t.ticket_id)}</p>
      <div id="mb-qr-display" class="mb-qr-display"></div>
      <dl class="ticket-facts"><div><dt>Loại xe</dt><dd>${vehicleLabel(t.vehicle_type)}</dd></div><div><dt>Giờ vào</dt><dd>${formatTime(t.entry_time)}</dd></div><div><dt>Giờ ra</dt><dd>${formatTime(t.exit_time)}</dd></div></dl>
      <p class="ticket-note">Giữ vé để đối chiếu khi lấy xe. Mã QR không xác nhận đã thu tiền.</p>
      <div class="row-actions no-print"><button type="button" class="btn btn-soft" id="ticket-print">In vé / phiếu thu</button><a class="btn btn-soft" href="${esc(data.qr_image)}" download="ve-${esc(t.ticket_id)}.png">Tải QR</a></div>
    </section><section class="ticket-charge"><h3>Phí gửi xe</h3><p>${badge(label,f.state==='paid'?'success':'warning')}</p><strong class="ticket-amount">${money(f.amount)}</strong>
      ${f.duration_minutes!=null?`<p class="ticket-note">Thời gian gửi: ${f.duration_minutes} phút</p>`:''}
      ${f.message?`<p class="ticket-note">${esc(f.message)}</p>`:''}${receiptHTML}
      ${f.payable && canWrite() ? `<form id="ticket-payment-form" class="no-print">
        <div class="form-row vertical"><label>Hình thức thu<select id="payment-method"><option value="cash" ${data.mb_auto_enabled&&f.amount>0?'':'selected'}>Tiền mặt</option><option value="mb" ${data.mb_auto_enabled&&f.amount>0?'selected':''}>MB tự động</option><option value="transfer">Chuyển khoản · xác nhận thủ công</option></select></label>
        <label id="payment-cash-label">Tiền khách đưa (đ)<input id="payment-received" type="number" min="${f.amount}" step="1" value="${f.amount}" required /></label></div>
        <p id="payment-change" class="ticket-note" role="status">Tiền thừa: ${money(0)}</p>
        <label class="billing-check" id="payment-confirm-label"><input id="payment-confirmed" type="checkbox" required />Tôi đã nhận đủ tiền</label>
        <p class="ticket-note" id="payment-manual-note">Ghi nhận thu tiền thủ công; không thực hiện giao dịch ngân hàng.</p>
        <p id="payment-error" class="workflow-error" role="alert" hidden></p>
        <button id="payment-submit" type="submit" class="btn btn-primary btn-block" disabled>Xác nhận đã thu ${money(f.amount)}</button>
        ${mbTransferMarkup()}
      </form>` : ''}
    </section></div>`;
    $('#ticket-print').addEventListener('click',()=>{ document.body.classList.add('printing-ticket'); window.print(); });
    if (f.payable && canWrite()) bindPayment(t.ticket_id,f,generation);
  } catch(error) {
    if (generation!==ticketPassGeneration || error.name==='AbortError') return;
    content.innerHTML=`<p role="alert">${esc(error.message)}</p><button class="btn btn-soft" id="ticket-retry">Thử lại</button>`;
    $('#ticket-retry').addEventListener('click',()=>openTicketPass(id));
  }
}
function bindPayment(id,finance,generation) {
  const method=$('#payment-method'), received=$('#payment-received'), confirm=$('#payment-confirmed'), button=$('#payment-submit');
  let pending=false;
  const mb=bindMBTransfer(id,generation);
  const update=()=>{
    const isMB=method.value==='mb', isCash=method.value==='cash', amount=Number(received.value);
    $('#ticket-dialog').dataset.paymentMode=method.value;
    $('#payment-confirm-label').hidden=isMB;confirm.required=!isMB;
    $('#payment-manual-note').hidden=isMB;$('#payment-change').hidden=isMB;button.hidden=isMB;
    $('#payment-cash-label').hidden=!isCash; received.required=isCash;
    $('#payment-change').textContent=isCash ? (Number.isSafeInteger(amount)&&amount>=finance.amount ? 'Tiền thừa: '+money(amount-finance.amount) : 'Tiền khách đưa chưa đủ hoặc không hợp lệ.') : 'Chỉ xác nhận sau khi kiểm tra tiền đã vào tài khoản.';
    button.disabled=isMB || pending || !confirm.checked || (isCash && (!Number.isSafeInteger(amount)||amount<finance.amount||amount>1000000000));
  };
  method.addEventListener('change',()=>{confirm.checked=false;update();if(method.value==='mb')mb.select();else mb.hide();}); received.addEventListener('input',update); confirm.addEventListener('change',update);
  $('#ticket-payment-form').addEventListener('submit',async event=>{
    event.preventDefault(); update();
    if (button.disabled || !canWrite() || pending) return;
    pending=true; button.disabled=true; const text=button.innerHTML; button.textContent='Đang ghi nhận…';
    $('#payment-error').hidden=true;
    try {
      await api('/tickets/'+encodeURIComponent(id)+'/payment',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({amount:finance.amount,quote_id:finance.quote_id,method:method.value,received_amount:method.value==='cash'?Number(received.value):finance.amount})});
      toast('Đã ghi nhận thu tiền.');
      if (generation===ticketPassGeneration) await openTicketPass(id);
    } catch(error) {
      if (generation===ticketPassGeneration) { $('#payment-error').textContent=error.message; $('#payment-error').hidden=false; }
    } finally {
      pending=false;
      if (generation===ticketPassGeneration) { button.innerHTML=text; update(); }
    }
  });
  update();if(method.value==='mb')mb.select();
}
function qrLookupMarkup() {
  return `<section class="qr-lookup"><label for="qr-ticket-input">Tìm vé bằng QR</label>
    <div class="qr-input-row"><input id="qr-ticket-input" placeholder="Dán mã QR hoặc dùng đầu đọc USB" autocomplete="off" maxlength="128" /><button class="btn btn-soft" type="button" id="qr-ticket-find">Tìm vé</button></div>
    <div class="row-actions"><button class="btn btn-soft" type="button" id="qr-camera-open">${icon('camera')}Quét camera</button><button class="btn btn-soft" type="button" id="qr-image-open">${icon('upload')}Ảnh QR</button></div>
    <input id="qr-image-file" type="file" accept="image/png,image/jpeg,image/webp" capture="environment" hidden />
    <div class="qr-camera-panel" id="qr-camera-panel" hidden><video id="qr-camera-video" autoplay muted playsinline></video><button class="btn btn-soft" type="button" id="qr-camera-close">Đóng camera QR</button></div>
    <p id="qr-ticket-status" class="ticket-note" role="status">Quét mã để chọn vé, sau đó đối chiếu ảnh xe ra.</p></section>`;
}
function bindQRLookup(onTicket) {
  const input=$('#qr-ticket-input'), status=$('#qr-ticket-status'), video=$('#qr-camera-video');
  let disposed=false, stream=null, cameraGeneration=0, request=0, timer, pending=false, fileVersion=0;
  const tell=text=>{status.textContent=text;};
  function stop() {
    cameraGeneration++; clearTimeout(timer);
    stream?.getTracks().forEach(track=>track.stop()); stream=null;
    if (video.srcObject) video.pause();
    video.srcObject=null; $('#qr-camera-panel').hidden=true; $('#qr-camera-open').disabled=false;
  }
  async function lookup(payload=input.value.trim()) {
    if (disposed || pending || !payload) return;
    if (!/^ITS1:[0-9a-f]{48}$/.test(payload)) {tell('Mã QR không phải vé ITS Parking hợp lệ.');return;}
    const version=++request; pending=true; $('#qr-ticket-find').disabled=true;
    tell('Đang tìm vé…');
    try {
      const data=await api('/tickets/lookup-qr',{method:'POST',body:new URLSearchParams({payload})});
      if (disposed || version!==request) return;
      await onTicket(data.ticket);
      tell('Đã tìm vé '+data.ticket.ticket_id+' · '+(data.ticket.plate_entry || 'Chưa rõ biển số'));
    } catch(error) { if (!disposed && version===request) tell(error.message); }
    finally { if (!disposed && version===request) { pending=false; $('#qr-ticket-find').disabled=false; } }
  }
  function decode(source,width,height) {
    const canvas=document.createElement('canvas'), scale=Math.min(1,1200/Math.max(width,height));
    canvas.width=Math.max(1,Math.round(width*scale)); canvas.height=Math.max(1,Math.round(height*scale));
    const ctx=canvas.getContext('2d',{willReadFrequently:true}); ctx.drawImage(source,0,0,canvas.width,canvas.height);
    const frame=ctx.getImageData(0,0,canvas.width,canvas.height);
    return jsQR(frame.data,frame.width,frame.height,{inversionAttempts:'attemptBoth'})?.data;
  }
  async function start() {
    if (disposed) return;
    stop(); const generation=cameraGeneration;
    $('#qr-camera-open').disabled=true; tell('Đang mở camera QR…');
    try {
      if (!globalThis.navigator?.mediaDevices?.getUserMedia) throw new Error('Camera cần HTTPS hoặc localhost. Bạn có thể chọn Ảnh QR hoặc dán mã vé.');
      const acquired=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1280}}});
      if (disposed || generation!==cameraGeneration) { acquired.getTracks().forEach(t=>t.stop()); return; }
      stream=acquired; video.srcObject=stream; $('#qr-camera-panel').hidden=false;
      stream.getTracks().forEach(t=>t.addEventListener('ended',()=>{if(stream===acquired){stop();tell('Camera đã ngắt. Kết nối lại hoặc chọn ảnh QR.');}}));
      await video.play();
      if (disposed || generation!==cameraGeneration) return;
      tell('Đưa mã QR vào khung hình.');
      const scan=()=>{
        if(disposed || generation!==cameraGeneration || !stream) return;
        try {
          if(video.readyState>=2 && video.videoWidth) {
            const payload=decode(video,video.videoWidth,video.videoHeight);
            if(payload) { stop(); input.value=payload; lookup(payload); return; }
          }
        } catch(_) { stop(); tell('Chưa đọc được camera. Hãy chọn ảnh QR hoặc dán mã vé.'); return; }
        timer=setTimeout(scan,200);
      };
      scan();
    } catch(error) {
      if(disposed || generation!==cameraGeneration) return;
      stop(); tell(error.name==='NotAllowedError'?'Chưa được cấp quyền camera. Cho phép trong trình duyệt hoặc chọn ảnh QR.':error.message || 'Không mở được camera QR.');
    }
  }
  $('#qr-camera-open').addEventListener('click',start);
  $('#qr-camera-close').addEventListener('click',stop);
  $('#qr-ticket-find').addEventListener('click',()=>lookup());
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();event.stopPropagation();lookup();}});
  const file=$('#qr-image-file');
  $('#qr-image-open').addEventListener('click',()=>{stop();file.value='';file.click();});
  file.addEventListener('change',async()=>{
    const selected=file.files[0], version=++fileVersion;
    if(!selected) return;
    if(!['image/png','image/jpeg','image/webp'].includes(selected.type)||selected.size>10*1024*1024) {tell('Chọn ảnh QR JPG, PNG hoặc WEBP dưới 10 MB.');return;}
    let bitmap;
    try {
      bitmap=await createImageBitmap(selected);
      if(disposed||version!==fileVersion) return;
      if(bitmap.width*bitmap.height>16000000) throw new Error('Ảnh quá lớn. Hãy cắt gọn vùng QR rồi thử lại.');
      const payload=decode(bitmap,bitmap.width,bitmap.height);
      if(!payload) {tell('Không đọc được QR trong ảnh. Hãy chọn ảnh rõ, đủ bốn góc mã.');return;}
      input.value=payload; await lookup(payload);
    } catch(error) {if(!disposed&&version===fileVersion)tell(error.message||'Ảnh QR không hợp lệ.');}
    finally {bitmap?.close();}
  });
  const visibility=()=>{if(document.hidden)stop();};
  document.addEventListener('visibilitychange',visibility); globalThis.addEventListener?.('pagehide',stop);
  cameraClosers.add(stop);
  previewCleanups.push(()=>{disposed=true;request++;fileVersion++;stop();cameraClosers.delete(stop);document.removeEventListener('visibilitychange',visibility);globalThis.removeEventListener?.('pagehide',stop);});
}

async function renderPricing() {
  const version=state.viewVersion;
  const data=await api('/pricing');
  if(state.view!=='pricing'||state.viewVersion!==version) return;
  $('#view-content').innerHTML=`<section class="card"><h3>Biểu phí gửi xe</h3><p class="pricing-intro">Khi cài mới, biểu phí mẫu ở trạng thái tắt. Chỉnh giá, chọn kích hoạt rồi lưu để áp dụng cho vé mới. Vé đang gửi giữ mức phí đã lưu lúc vào bãi.</p>
    <div class="pricing-grid">${data.items.map(p=>`<form class="pricing-form" data-pricing="${p.vehicle_type}"><h3>${vehicleLabel(p.vehicle_type)}</h3>
      <label class="billing-check"><input name="enabled" type="checkbox" ${p.enabled?'checked':''} />Kích hoạt cho vé mới</label>
      <div class="form-row vertical"><label>Cách tính<select name="mode"><option value="hourly" ${p.mode==='hourly'?'selected':''}>Theo thời gian</option><option value="flat" ${p.mode==='flat'?'selected':''}>Theo lượt</option></select></label>
      <label data-flat>Giá mỗi lượt (đ)<input name="flat_amount" type="number" min="0" max="10000000" step="1" value="${p.flat_amount}" required /></label>
      <div class="pricing-hourly" data-hourly>${[['first_minutes','Khoảng đầu (phút)',1,1440],['first_amount','Giá khoảng đầu (đ)',0,10000000],['next_minutes','Khoảng tiếp theo (phút)',1,1440],['next_amount','Giá mỗi khoảng tiếp theo (đ)',0,10000000],['daily_cap','Tối đa mỗi 24 giờ (đ) · 0 là không giới hạn',0,10000000]].map(([key,label,min,max])=>`<label>${label}<input name="${key}" type="number" min="${min}" max="${max}" step="1" value="${p[key]}" required /></label>`).join('')}</div>
      <label>Miễn phí nếu gửi không quá (phút)<input name="grace_minutes" type="number" min="0" max="1440" step="1" value="${p.grace_minutes}" required /></label></div>
      <p class="ticket-note">Làm tròn lên theo phút và khoảng tính phí. Quá thời gian miễn phí sẽ tính từ giờ vào. Mức trần áp dụng cho từng 24 giờ liên tục.</p>
      <p class="pricing-status ticket-note" role="status"></p><button type="submit" class="btn btn-primary">Lưu biểu phí ${vehicleLabel(p.vehicle_type).toLowerCase()}</button>
    </form>`).join('')}</div></section>`;
  document.querySelectorAll('[data-pricing]').forEach(form=>{
    const current=data.items.find(p=>p.vehicle_type===form.dataset.pricing);
    const mode=form.querySelector('[name="mode"]'), status=form.querySelector('.pricing-status');
    const sync=()=>{form.querySelector('[data-flat]').hidden=mode.value!=='flat';form.querySelector('[data-hourly]').hidden=mode.value!=='hourly';};
    mode.addEventListener('change',sync); sync();
    form.addEventListener('submit',async event=>{
      event.preventDefault(); const button=form.querySelector('button[type="submit"]');
      if(button.disabled) return;
      const payload={revision:current.revision,enabled:form.querySelector('[name="enabled"]').checked,mode:mode.value};
      ['flat_amount','first_minutes','first_amount','next_minutes','next_amount','daily_cap','grace_minutes'].forEach(key=>{payload[key]=Number(form.querySelector('[name="'+key+'"]').value);});
      button.disabled=true; status.textContent='Đang lưu…';
      try {
        const data=await api('/pricing/'+form.dataset.pricing,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        current.revision=data.tariff.revision;
        status.textContent=data.tariff.enabled?'Đã lưu và kích hoạt cho vé mới.':'Đã lưu. Biểu phí đang tắt.';
      } catch(error) {status.textContent=error.message;}
      finally {button.disabled=false;}
    });
  });
}
function initTicketTools() {
  initQuickPaymentQR();
  document.addEventListener('click',event=>{const button=event.target.closest?.('[data-ticket-pass]');if(button)openTicketPass(button.dataset.ticketPass);const quick=event.target.closest?.('[data-quick-payment]');if(quick)openQuickPaymentQR(quick.dataset.quickPayment);});
  $('#ticket-dialog-close').addEventListener('click',closeTicketPass);
  $('#ticket-dialog').addEventListener('cancel',()=>{stopMBTransfer();ticketPassGeneration++;ticketPassController?.abort();ticketPassData=null;});
  globalThis.addEventListener?.('afterprint',()=>document.body.classList.remove('printing-ticket'));
}
