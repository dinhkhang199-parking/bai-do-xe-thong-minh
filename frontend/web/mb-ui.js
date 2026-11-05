/* global $, api, esc, formatTime, money, openTicketPass, previewCleanups, state, ticketPassGeneration, toast */
/* exported mbTransferMarkup, bindMBTransfer, renderMB */
'use strict';

function createVisibilityPoller() {
  let timer = null,
    pending = null,
    disposed = false;
  function clear() {
    clearTimeout(timer);
    timer = null;
    pending = null;
  }
  function schedule(callback, delay) {
    clear();
    if (disposed) return;
    pending = callback;
    if (!document.hidden)
      timer = setTimeout(() => {
        timer = null;
        if (disposed || document.hidden) return;
        const task = pending;
        pending = null;
        return task?.();
      }, delay);
  }
  function visibility() {
    if (document.hidden) {
      clearTimeout(timer);
      timer = null;
    } else if (pending && !disposed) schedule(pending, 0);
  }
  document.addEventListener?.('visibilitychange', visibility);
  return {
    schedule,
    clear,
    dispose() {
      disposed = true;
      clear();
      document.removeEventListener?.('visibilitychange', visibility);
    },
  };
}

function mbMonitorMessage(monitor) {
  if (monitor?.state === 'disabled')
    return 'Tự đối soát MB đang tắt. Nhờ quản trị viên kiểm tra Kết nối MB.';
  if (!monitor || typeof monitor.running !== 'boolean')
    return 'Chưa xác định được trạng thái tự đối soát MB. Cập nhật trạng thái để kiểm tra lại.';
  if (!monitor.running)
    return 'Dịch vụ tự đối soát MB đang dừng. Nhờ quản trị viên kiểm tra; các yêu cầu đã lưu vẫn được giữ lại.';
  if (monitor.last_error) return monitor.last_error;
  if (monitor.state === 'unavailable')
    return 'Chưa đọc được tiền vào MB. Nhờ quản trị viên kiểm tra Kết nối MB.';
  if (!['idle', 'ready', 'checking'].includes(monitor.state))
    return 'Đang kiểm tra kết nối MB; chưa xác nhận tự đối soát sẵn sàng.';
  return 'MB đang tự đối soát tiền vào. Không cần bấm xác nhận đã chuyển; đóng cửa sổ QR vẫn được theo dõi.';
}

let mbTransferCleanup = null;
function stopMBTransfer() {
  mbTransferCleanup?.();
  mbTransferCleanup = null;
}
function mbTransferMarkup() {
  return `<section id="mb-transfer-panel" class="mb-transfer-panel" hidden>
    <p class="ticket-note">Quét mã chuyển khoản, kiểm tra người nhận và giữ nguyên nội dung.</p>
    <button type="button" class="btn btn-primary btn-block" id="mb-create-order">Tạo mã chuyển khoản MB</button>
    <div id="mb-order-content"></div><p id="mb-order-message" class="ticket-note" role="status"></p>
  </section>`;
}
function bindMBTransfer(ticketId, generation) {
  stopMBTransfer();
  let disposed = false,
    pending = false,
    controller = null;
  const poller = createVisibilityPoller();
  const panel = $('#mb-transfer-panel'),
    content = $('#mb-order-content'),
    message = $('#mb-order-message'),
    create = $('#mb-create-order');
  const active = () => !disposed && generation === ticketPassGeneration && $('#ticket-dialog').open;
  const selected = () => active() && $('#payment-method').value === 'mb';
  const tell = (text) => {
    if (active()) message.textContent = text;
  };
  const clear = () => {
    poller.clear();
    controller?.abort();
  };
  async function check() {
    if (!selected() || pending) return;
    pending = true;
    clear();
    tell('Đang đối chiếu giao dịch MB…');
    const button = $('#mb-check-order');
    if (button) button.disabled = true;
    try {
      controller = new AbortController();
      const data = await api('/tickets/' + encodeURIComponent(ticketId) + '/mb-order', {
        signal: controller.signal,
      });
      if (!active()) return;
      if (data.matched || data.order?.status === 'paid') {
        stopMBTransfer();
        toast('MB đã đối soát khoản thu.');
        await openTicketPass(ticketId);
        return;
      }
      paint(data.order);
      tell(mbMonitorMessage(data.monitor));
    } catch (error) {
      if (error.name !== 'AbortError') {
        tell(error.message);
        if (selected()) poller.schedule(check, 5000);
      }
    } finally {
      pending = false;
      if (active() && $('#mb-check-order')) $('#mb-check-order').disabled = false;
    }
  }
  function paint(order) {
    clear();
    if (!active()) return;
    create.disabled = !!order && order.status === 'pending';
    create.hidden = !!order && order.status === 'pending';
    $('#mb-qr-display').innerHTML = '';
    if (!order) {
      content.innerHTML = '';
      return;
    }
    if (order.status === 'paid') {
      stopMBTransfer();
      openTicketPass(ticketId);
      return;
    }
    const pendingOrder = order.status === 'pending';
    if (pendingOrder)
      $('#mb-qr-display').innerHTML =
        `<img class="mb-transfer-qr" src="${esc(order.qr_image)}" alt="QR chuyển khoản MB" /><p class="ticket-note">QR chuyển khoản MB · ${money(order.amount)}</p>`;
    content.innerHTML = `
      <dl class="ticket-facts"><div><dt>Ngân hàng</dt><dd>MB</dd></div><div><dt>Tài khoản nhận</dt><dd>${esc(order.account_no)}</dd></div><div><dt>Người nhận</dt><dd>${esc(order.account_name)}</dd></div><div><dt>Số tiền</dt><dd>${money(order.amount)}</dd></div><div><dt>Nội dung</dt><dd class="mb-code">${esc(order.code)}</dd></div><div><dt>Hạn mã</dt><dd>${formatTime(order.expires_at)}</dd></div></dl>
      ${!pendingOrder ? '<p class="ticket-note">Mã đã hết hạn hoặc đã dừng. Nếu khách đã chuyển, kiểm tra giao dịch trước khi tạo mã mới.</p>' : ''}
      <div class="row-actions">${['pending', 'expired'].includes(order.status) ? '<button type="button" class="btn btn-soft" id="mb-check-order">Cập nhật trạng thái</button>' : ''}${pendingOrder ? '<button type="button" class="btn btn-soft" id="mb-cancel-order">Dừng mã</button>' : ''}</div>`;
    $('#mb-check-order')?.addEventListener('click', check);
    $('#mb-cancel-order')?.addEventListener('click', async () => {
      if (pending) return;
      pending = true;
      clear();
      try {
        const data = await api('/tickets/' + encodeURIComponent(ticketId) + '/mb-order/cancel', {
          method: 'POST',
        });
        if (active()) {
          paint(data.order);
          tell('Đã dừng mã. Thao tác này không hoàn tiền ngân hàng.');
        }
      } catch (error) {
        tell(error.message);
      } finally {
        pending = false;
      }
    });
    if (pendingOrder && selected()) poller.schedule(check, 1000);
  }
  async function load() {
    if (!selected() || pending) return;
    pending = true;
    clear();
    try {
      controller = new AbortController();
      const data = await api('/tickets/' + encodeURIComponent(ticketId) + '/mb-order', {
        signal: controller.signal,
      });
      paint(data.order);
      tell(mbMonitorMessage(data.monitor));
    } catch (error) {
      if (error.name !== 'AbortError') tell(error.message);
    } finally {
      pending = false;
    }
  }
  create.addEventListener('click', async () => {
    if (!selected() || pending) return;
    pending = true;
    create.disabled = true;
    tell('Đang tạo mã chuyển khoản…');
    try {
      const data = await api('/tickets/' + encodeURIComponent(ticketId) + '/mb-order', {
        method: 'POST',
      });
      if (active()) {
        paint(data.order);
        tell('Quét bằng ứng dụng ngân hàng. Kiểm tra tên người nhận trước khi chuyển.');
      }
    } catch (error) {
      tell(error.message);
      if (active()) create.disabled = false;
    } finally {
      pending = false;
    }
  });
  mbTransferCleanup = () => {
    disposed = true;
    clear();
    poller.dispose();
  };
  return {
    select() {
      panel.hidden = false;
      load();
    },
    hide() {
      panel.hidden = true;
      clear();
    },
  };
}

async function renderMB() {
  const version = state.viewVersion;
  $('#view-content').innerHTML = `<section class="card mb-settings"><h3>Kết nối MB</h3>
    <p class="pricing-intro">Đối chiếu tiền chuyển vào để ghi nhận phí gửi xe. Dịch vụ này không chuyển tiền hoặc hoàn tiền. Thông tin đăng nhập được đọc từ cấu hình MB trên máy chủ.</p>
    <p id="mb-connection-state" role="status">Đang kiểm tra dịch vụ…</p><p id="mb-admin-message" class="ticket-note" role="status"></p><p id="mb-failure-detail" class="ticket-note" hidden></p>
    <div class="form-row"><label>Giải CAPTCHA<select id="mb-captcha-mode"><option value="manual">Nhập tay</option><option id="mb-local-option" value="local" disabled>Tự động trên máy chủ</option><option id="mb-ecaptcha-option" value="ecaptcha" disabled>Tự động bằng Ecaptcha</option></select></label></div>
    <p id="mb-captcha-service-note" class="ticket-note"></p>
    <div class="row-actions"><button class="btn btn-primary" id="mb-connect" type="button">Kết nối MB</button><button class="btn btn-soft" id="mb-refresh" type="button">Cập nhật trạng thái</button><button class="btn btn-soft" id="mb-disconnect" type="button">Ngắt phiên MB</button></div>
    <div id="mb-captcha-box"></div>
    <form id="mb-settings-form" class="mb-settings-form"><h3>Tài khoản nhận phí</h3>
      <p id="mb-config-conflict" role="alert" hidden>Cấu hình MB đã được thay đổi ở phiên khác. Nạp cấu hình mới trước khi chỉnh sửa và lưu.</p><button class="btn btn-soft" id="mb-reload-settings" type="button" hidden>Nạp cấu hình mới</button>
      <div class="form-row vertical"><label>Tài khoản VND đã xác minh<select id="mb-receiver"><option value="">Kết nối MB để chọn tài khoản</option></select></label></div>
      <label class="billing-check"><input id="mb-enabled" type="checkbox" />Kích hoạt chuyển khoản MB cho phiếu thu</label>
      <p class="ticket-note">Mỗi mã chuyển khoản có hiệu lực 15 phút. Đổi tài khoản hoặc tắt tích hợp sẽ dừng các mã đang chờ. Biểu phí gửi xe vẫn cần được kích hoạt riêng.</p>
      <button class="btn btn-primary" id="mb-save" type="submit">Lưu cấu hình MB</button>
    </form></section>`;
  const poller = createVisibilityPoller();
  let disposed = false,
    config = null,
    captchaId = '',
    accountsKey = '',
    busy = false,
    modeInitialized = false;
  let refreshSequence = 0,
    refreshController,
    connection = null,
    configConflict = false,
    submittedCaptchaId = '';
  const valid = () => !disposed && state.viewVersion === version && state.view === 'mb';
  const msg = (text) => {
    if (valid()) $('#mb-admin-message').textContent = text;
  };
  const cancelRefresh = () => {
    poller.clear();
    refreshController?.abort();
    refreshSequence++;
  };
  function syncControls() {
    if (!valid()) return;
    const pending = ['connected', 'connecting', 'captcha_required', 'captcha_solving'].includes(
      connection?.state,
    );
    $('#mb-connect').disabled =
      busy ||
      pending ||
      connection?.credentials_present === false ||
      connection?.library_present === false;
    $('#mb-disconnect').disabled =
      busy || ['disconnected', 'unavailable'].includes(connection?.state);
    $('#mb-refresh').disabled = busy;
    $('#mb-save').disabled = busy || configConflict || !config;
    $('#mb-captcha-mode').disabled = busy || pending;
    if ($('#mb-captcha-submit'))
      $('#mb-captcha-submit').disabled = busy || (!!captchaId && submittedCaptchaId === captchaId);
  }
  function paint(data, resetSettings = false) {
    if (!valid()) return;
    if (!config || resetSettings) {
      config = data.settings;
      $('#mb-enabled').checked = config.enabled;
      accountsKey = '';
      configConflict = false;
    } else configConflict = data.settings.revision !== config.revision;
    $('#mb-config-conflict').hidden = $('#mb-reload-settings').hidden = !configConflict;
    connection = data.connection;
    const service = connection.captcha_service;
    const localReady = !!connection.local_captcha?.configured;
    $('#mb-local-option').disabled = !localReady;
    $('#mb-ecaptcha-option').disabled = !service?.configured;
    if (!modeInitialized) {
      $('#mb-captcha-mode').value = localReady
        ? 'local'
        : service?.configured
          ? 'ecaptcha'
          : 'manual';
      modeInitialized = true;
    } else if (!service?.configured && $('#mb-captcha-mode').value === 'ecaptcha') {
      $('#mb-captcha-mode').value = 'manual';
    }
    if (!localReady && $('#mb-captcha-mode').value === 'local')
      $('#mb-captcha-mode').value = 'manual';
    $('#mb-captcha-service-note').textContent = localReady
      ? 'Bộ giải MB cục bộ đã sẵn sàng. Ảnh được xử lý trên máy chủ; mã chưa rõ sẽ chuyển sang nhập tay. Chỉ chạy khi bạn bấm Kết nối MB.'
      : service?.configured
        ? 'Đã có cấu hình Ecaptcha. Chế độ tự động chỉ gửi ảnh CAPTCHA tới ecaptcha.shopcode.top, không gửi tên đăng nhập hay mật khẩu MB. Dịch vụ lỗi sẽ chuyển sang nhập tay.'
        : 'Chưa có cấu hình Ecaptcha hợp lệ. Bạn vẫn có thể nhập CAPTCHA trực tiếp.';
    const labels = {
      disconnected: 'Chưa đăng nhập MB',
      connecting: 'Đang kết nối MB…',
      captcha_solving: 'Đang đọc CAPTCHA…',
      captcha_required: 'Cần nhập CAPTCHA',
      connected: 'Đã kết nối MB',
      error: 'Cần kết nối lại',
      unavailable: 'Dịch vụ MB chưa sẵn sàng',
    };
    $('#mb-connection-state').textContent =
      labels[connection.state] || 'Chưa xác định trạng thái MB';
    msg(
      connection.message ||
        (connection.credentials_present === false
          ? 'Chưa có thông tin đăng nhập MB trên máy chủ.'
          : connection.library_present === false
            ? 'Thiếu thư viện kết nối MB trên máy chủ.'
            : ''),
    );
    const failure = connection.failure;
    const stages = {
      initialization: 'Khởi tạo',
      captcha: 'Nhận CAPTCHA',
      encryption: 'Mã hóa đăng nhập',
      login: 'Đăng nhập',
      verification: 'Xác minh MB',
      accounts: 'Đọc tài khoản',
      history: 'Đọc giao dịch',
    };
    $('#mb-failure-detail').hidden = !failure;
    $('#mb-failure-detail').textContent = failure
      ? `Bước: ${stages[failure.stage] || 'Kết nối MB'}${failure.bank_code ? ' · Mã MB: ' + failure.bank_code : ''}${failure.http_status ? ' · HTTP ' + failure.http_status : ''}`
      : '';
    const accounts = connection.accounts || [],
      key = JSON.stringify(accounts);
    if (key !== accountsKey) {
      accountsKey = key;
      const selected = resetSettings
        ? config.account_no
        : $('#mb-receiver').value || config.account_no;
      $('#mb-receiver').innerHTML =
        '<option value="">Chọn tài khoản nhận</option>' +
        accounts
          .map(
            (account) =>
              `<option value="${esc(account.account)}">${esc(account.account)} · ${esc(account.name)}</option>`,
          )
          .join('') +
        (!accounts.some((a) => a.account === config.account_no) && config.account_no
          ? `<option value="${esc(config.account_no)}">Đã lưu · …${esc(config.account_no.slice(-4))} (chưa xác minh phiên)</option>`
          : '');
      $('#mb-receiver').value = selected;
    }
    const captcha = connection.captcha;
    if ((captcha?.id || '') !== captchaId) {
      captchaId = captcha?.id || '';
      $('#mb-captcha-box').innerHTML = captcha
        ? `<form id="mb-captcha-form" class="mb-captcha-form"><label for="mb-captcha-text">Nhập CAPTCHA từ MB</label><img src="${esc(captcha.image)}" alt="CAPTCHA đăng nhập MB" /><input id="mb-captcha-text" autocomplete="off" autocapitalize="off" spellcheck="false" minlength="4" maxlength="12" pattern="[A-Za-z0-9]+" required /><button class="btn btn-soft" id="mb-captcha-submit" type="submit">Gửi CAPTCHA</button></form>`
        : '';
      $('#mb-captcha-form')?.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (busy || !valid() || submittedCaptchaId === captchaId) return;
        const payload = { id: captchaId, text: $('#mb-captcha-text').value.trim() };
        busy = true;
        cancelRefresh();
        syncControls();
        try {
          await api('/mb/captcha', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          submittedCaptchaId = payload.id;
          msg('Đã gửi mã, đang chờ MB.');
        } catch (error) {
          msg(error.message);
        } finally {
          busy = false;
          if (valid()) {
            syncControls();
            poller.schedule(() => refresh(), 1000);
          }
        }
      });
    }
    syncControls();
  }
  async function refresh(resetSettings = false) {
    if (!valid()) return;
    cancelRefresh();
    const current = refreshSequence;
    refreshController = new AbortController();
    try {
      const data = await api('/mb/status', { signal: refreshController.signal });
      if (valid() && current === refreshSequence) paint(data, resetSettings);
    } catch (error) {
      if (valid() && current === refreshSequence && error.name !== 'AbortError') {
        $('#mb-connection-state').textContent = 'Chưa cập nhật được trạng thái MB';
        $('#mb-failure-detail').hidden = true;
        msg(error.message);
      }
    } finally {
      if (valid() && current === refreshSequence)
        poller.schedule(
          () => refresh(),
          ['connecting', 'captcha_required', 'captcha_solving'].includes(connection?.state)
            ? 3000
            : 5000,
        );
    }
  }
  async function action(path) {
    if (busy || !valid()) return;
    busy = true;
    cancelRefresh();
    syncControls();
    const options = { method: 'POST' };
    if (path === '/mb/connect') {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify({ captcha_mode: $('#mb-captcha-mode').value });
    }
    try {
      await api(path, options);
      if (valid()) {
        msg('');
        await refresh();
      }
    } catch (error) {
      msg(error.message);
      if (valid()) poller.schedule(() => refresh(), 5000);
    } finally {
      busy = false;
      syncControls();
    }
  }
  $('#mb-connect').addEventListener('click', () => action('/mb/connect'));
  $('#mb-disconnect').addEventListener('click', () => action('/mb/disconnect'));
  $('#mb-refresh').addEventListener('click', () => refresh());
  $('#mb-reload-settings').addEventListener('click', () => refresh(true));
  $('#mb-settings-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!config || busy || configConflict || !valid()) return;
    busy = true;
    cancelRefresh();
    syncControls();
    try {
      const data = await api('/mb/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_no: $('#mb-receiver').value,
          enabled: $('#mb-enabled').checked,
          revision: config.revision,
        }),
      });
      if (valid()) {
        config = data.settings;
        msg(config.enabled ? 'Đã kích hoạt chuyển khoản MB.' : 'Đã tắt chuyển khoản MB.');
      }
    } catch (error) {
      msg(error.message);
    } finally {
      busy = false;
      if (valid()) {
        syncControls();
        poller.schedule(() => refresh(), 5000);
      }
    }
  });
  previewCleanups.push(() => {
    disposed = true;
    cancelRefresh();
    poller.dispose();
  });
  await refresh();
}
