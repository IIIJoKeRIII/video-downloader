/* ---------- мост к Python ---------- */

// Единственная точка вызова Python. Никогда не бросает: отказ моста
// (исключение в Python, неизвестный метод) приходит обычным ответом
// с ok:false, и каждому месту не нужно ловить его отдельно.
async function call(name, ...args) {
  try {
    const bridge = window.pywebview && window.pywebview.api;
    const fn = bridge && bridge[name];
    if (typeof fn !== 'function') {
      return { ok: false, error: 'Внутренняя ошибка приложения.', error_detail: 'Нет метода ' + name };
    }
    return await fn(...args);
  } catch (e) {
    return { ok: false, error: 'Внутренняя ошибка приложения.', error_detail: (e && e.message) || String(e) };
  }
}

const btn = document.getElementById('btn');
const stopBtn = document.getElementById('stopBtn');
const urlInput = document.getElementById('url');
const status = document.getElementById('status');
const progressWrap = document.getElementById('progressWrap');
const progressFill = document.getElementById('progressFill');
const progressName = document.getElementById('progressName');
const progressStat = document.getElementById('progressStat');
const dropZone = document.getElementById('dropZone');
const footHint = document.getElementById('footHint');
const quality = document.getElementById('quality');

const updateBanner = document.getElementById('updateBanner');
const updateText = document.getElementById('updateText');
const updateBtn = document.getElementById('updateBtn');
const updateNote = document.getElementById('updateNote');

let pollTimer = null;
let currentJobId = null;
let updateTimer = null;
let currentScreen = 'download';
let historyTimer = null;

/* ---------- переключение экранов ---------- */

function showScreen(name) {
  currentScreen = name;
  document.querySelectorAll('.screen').forEach((el) => {
    el.classList.toggle('active', el.id === 'screen-' + name);
  });
  document.querySelectorAll('.navitem').forEach((el) => {
    el.classList.toggle('active', el.dataset.screen === name);
  });

  if (historyTimer) { clearInterval(historyTimer); historyTimer = null; }
  if (name === 'history') {
    loadHistory();
    historyTimer = setInterval(loadHistory, 1000);
  }
}

function pauseHistoryPolling() {
  if (historyTimer) { clearInterval(historyTimer); historyTimer = null; }
}

function resumeHistoryPolling() {
  if (currentScreen === 'history' && !historyTimer) {
    historyTimer = setInterval(loadHistory, 1000);
  }
}

document.querySelectorAll('.navitem').forEach((el) => {
  el.addEventListener('click', () => showScreen(el.dataset.screen));
});

/* ---------- экран «Скачать» ---------- */

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec) return '';
  const mb = bytesPerSec / (1024 * 1024);
  if (mb >= 1) return mb.toFixed(1) + ' МБ/с';
  return (bytesPerSec / 1024).toFixed(0) + ' КБ/с';
}

function setFormState(state) {
  const busy = state === 'downloading';
  btn.style.display = busy ? 'none' : 'inline-block';
  btn.disabled = urlInput.value.trim() === '';
  stopBtn.style.display = busy ? 'inline-block' : 'none';
  urlInput.readOnly = busy;
  quality.disabled = busy;
  progressWrap.style.display = busy ? 'block' : 'none';
  dropZone.style.display = (state === 'idle' && urlInput.value.trim() === '') ? 'block' : 'none';
  urlInput.classList.toggle('error-border', state === 'error');

  if (state === 'downloading') {
    footHint.textContent = 'Можно остановить в любой момент — файл не сохранится.';
  } else {
    footHint.textContent = 'Поддерживаются сайты, где работает yt-dlp.';
  }
}

function errorKindClass(kind) {
  return kind === 'disk' ? 'warn' : 'danger';
}

function showError(message, detail, kind) {
  stopPolling();
  setFormState('error');
  status.innerHTML = '';

  const box = document.createElement('div');
  box.className = 'msg-box ' + errorKindClass(kind);

  const title = document.createElement('div');
  title.className = 'msg-title';
  title.textContent = message || 'Ошибка загрузки';
  box.appendChild(title);

  if (detail) {
    const det = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'Подробности';
    const body = document.createElement('div');
    body.className = 'detail';
    body.textContent = detail;
    det.appendChild(summary);
    det.appendChild(body);
    box.appendChild(det);
  }
  status.appendChild(box);
}

function showFinished(filename, title) {
  status.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'msg-box ok';

  const text = document.createElement('div');
  text.className = 'msg-title';
  text.textContent = 'Готово: ' + title;
  box.appendChild(text);

  const link = document.createElement('a');
  link.href = '#';
  link.className = 'msg-action';
  link.textContent = 'Показать в папке';
  link.addEventListener('click', (ev) => {
    ev.preventDefault();
    call('reveal_file', filename);
  });
  box.appendChild(link);
  status.appendChild(box);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollProgress() {
  if (!currentJobId) return;
  const data = await call('get_progress', currentJobId);

  if (!data.ok) {
    showError(data.error || 'Ошибка', data.error_detail);
    return;
  }

  const playlistPart = (data.playlist_index && data.playlist_count)
    ? 'Видео ' + data.playlist_index + ' из ' + data.playlist_count + ' · '
    : '';
  progressName.textContent = playlistPart + (data.current_name || 'Загрузка…');
  if (data.progress !== null && data.progress !== undefined) {
    progressFill.style.width = data.progress + '%';
    progressStat.textContent = data.progress + '% · ' + formatSpeed(data.speed);
  } else {
    progressStat.textContent = formatSpeed(data.speed);
  }

  if (data.status === 'finished') {
    stopPolling();
    setFormState('idle');
    showFinished(data.filename, data.title);
    currentJobId = null;
    if (currentScreen === 'history') loadHistory();
  } else if (data.status === 'cancelled') {
    stopPolling();
    setFormState('idle');
    status.innerHTML = '';
    status.textContent = 'Скачивание остановлено';
    currentJobId = null;
  } else if (data.status === 'error') {
    showError(data.error, data.error_detail, data.error_kind);
    currentJobId = null;
  }
}

async function startDownload() {
  const url = urlInput.value.trim();
  if (!url) return;

  setFormState('downloading');
  status.innerHTML = '';
  progressFill.style.width = '0%';
  progressName.textContent = 'Загрузка…';
  progressStat.textContent = '';

  const data = await call('start_download', url, Number(quality.value));
  if (!data.ok) {
    showError(data.error, data.error_detail);
    return;
  }

  currentJobId = data.job_id;
  pollTimer = setInterval(pollProgress, 500);
}

async function stopDownload() {
  if (!currentJobId) return;
  stopBtn.disabled = true;
  await call('cancel', currentJobId);
  stopBtn.disabled = false;
}

/* ---------- дропзона и вставка ---------- */

function goToUrl(text) {
  urlInput.value = text;
  setFormState('idle');
}

dropZone.addEventListener('click', () => urlInput.focus());
dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  const text = e.dataTransfer.getData('text');
  if (text) goToUrl(text);
});
document.addEventListener('paste', (e) => {
  if (document.activeElement === urlInput) return;
  const text = e.clipboardData.getData('text');
  if (text) goToUrl(text);
});
urlInput.addEventListener('input', () => {
  btn.disabled = urlInput.value.trim() === '';
  dropZone.style.display = urlInput.value.trim() === '' ? 'block' : 'none';
});

/* ---------- обновления ---------- */

function renderUpdate(data) {
  if (data.state === 'available') {
    updateBanner.style.display = 'block';
    updateText.textContent = 'Есть новая версия ' + data.latest_version +
                             ' (у вас ' + data.current_version + ')';
    updateBtn.style.display = 'inline-block';
    updateBtn.disabled = false;
    updateNote.textContent = '';
  } else if (data.state === 'downloading') {
    updateBanner.style.display = 'block';
    updateBtn.disabled = true;
    updateNote.textContent = 'Скачиваю установщик… ' +
      (data.progress === null || data.progress === undefined ? '' : data.progress + '%');
  } else if (data.state === 'installing') {
    updateBanner.style.display = 'block';
    updateBtn.disabled = true;
    updateNote.textContent = 'Установщик запущен, приложение закроется.';
  } else if (data.state === 'install_error') {
    updateBanner.style.display = 'block';
    updateBtn.disabled = false;
    updateNote.textContent = data.error || 'Не удалось обновиться';
  } else {
    // up_to_date, no_releases, no_asset, unavailable, disabled — молчим.
    updateBanner.style.display = 'none';
  }

  if (data.state !== 'checking' && data.state !== 'downloading' && updateTimer) {
    clearInterval(updateTimer);
    updateTimer = null;
  }
}

async function checkUpdate() {
  // Обновления не критичны: отказ ответа просто прячет баннер.
  renderUpdate(await call('get_update_state'));
}

function watchUpdate() {
  checkUpdate();
  if (!updateTimer) updateTimer = setInterval(checkUpdate, 1500);
}

updateBtn.addEventListener('click', async () => {
  updateBtn.disabled = true;
  await call('install_update');
  watchUpdate();
});

/* ---------- качество: селект и пилюли синхронно ---------- */

function applyQuality(height) {
  quality.value = String(height);
  document.querySelectorAll('.pill').forEach((el) => {
    el.classList.toggle('active', Number(el.dataset.height) === Number(height));
  });
  call('set_quality', Number(height));
}

quality.addEventListener('change', () => applyQuality(quality.value));

/* ---------- история ---------- */

const historyList = document.getElementById('historyList');
const historyEmpty = document.getElementById('historyEmpty');

function formatMeta(item) {
  const parts = [];
  if (item.height) parts.push(item.height + 'p');
  parts.push(item.size_text);
  parts.push(item.when);
  return parts.join(' · ');
}

function buildActiveRow(item) {
  const row = document.createElement('div');
  row.className = 'hrow';

  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  row.appendChild(thumb);

  const main = document.createElement('div');
  main.className = 'hmain';
  const name = document.createElement('div');
  name.className = 'hname';
  name.textContent = item.title;
  main.appendChild(name);
  const bar = document.createElement('div');
  bar.className = 'hbar';
  const fill = document.createElement('div');
  fill.className = 'hbar-fill';
  fill.style.width = (item.progress || 0) + '%';
  bar.appendChild(fill);
  main.appendChild(bar);
  row.appendChild(main);

  const percent = document.createElement('span');
  percent.className = 'hpercent';
  percent.textContent = (item.progress !== null && item.progress !== undefined) ? item.progress + '%' : '';
  row.appendChild(percent);

  const stop = document.createElement('button');
  stop.className = 'haction stop';
  stop.textContent = 'Стоп';
  stop.addEventListener('click', async () => {
    await call('cancel', item.job_id);
    loadHistory();
  });
  row.appendChild(stop);

  return row;
}

function buildCancelledRow(item) {
  const row = document.createElement('div');
  row.className = 'hrow cancelled';

  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  row.appendChild(thumb);

  const main = document.createElement('div');
  main.className = 'hmain';
  const name = document.createElement('div');
  name.className = 'hname';
  name.textContent = item.title;
  main.appendChild(name);
  const meta = document.createElement('div');
  meta.className = 'hmeta';
  meta.textContent = 'Остановлено пользователем';
  main.appendChild(meta);
  row.appendChild(main);

  const retry = document.createElement('button');
  retry.className = 'haction retry';
  retry.textContent = 'Повторить';
  retry.addEventListener('click', async () => {
    const data = await call('start_download', item.url, item.height);
    if (data.ok) {
      currentJobId = data.job_id;
      urlInput.value = item.url;
      setFormState('downloading');
      status.innerHTML = '';
      progressFill.style.width = '0%';
      progressName.textContent = 'Загрузка…';
      progressStat.textContent = '';
      pollTimer = setInterval(pollProgress, 500);
      showScreen('download');
    }
  });
  row.appendChild(retry);

  return row;
}

function buildDoneRow(item) {
  const row = document.createElement('div');
  row.className = 'hrow';

  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  row.appendChild(thumb);

  const main = document.createElement('div');
  main.className = 'hmain';
  const name = document.createElement('div');
  name.className = 'hname';
  name.textContent = item.title;
  main.appendChild(name);
  const meta = document.createElement('div');
  meta.className = 'hmeta';
  meta.textContent = formatMeta(item);
  main.appendChild(meta);
  const errNote = document.createElement('div');
  errNote.className = 'hnote-error';
  main.appendChild(errNote);
  row.appendChild(main);

  const actions = document.createElement('div');
  actions.style.display = 'flex';
  actions.style.gap = '8px';
  actions.style.alignItems = 'center';

  const folder = document.createElement('button');
  folder.className = 'haction folder';
  folder.textContent = 'Папка';
  folder.addEventListener('click', () => {
    call('reveal_file', item.filename);
  });
  actions.appendChild(folder);

  const remove = document.createElement('button');
  remove.className = 'haction remove';
  remove.textContent = '×';
  remove.addEventListener('click', () => {
    // Полный список перерисовывается раз в секунду (loadHistory); пока
    // открыт вопрос «Удалить файл?», опрос приостанавливаем — иначе
    // подтверждение может исчезнуть посреди клика пользователя.
    pauseHistoryPolling();

    actions.innerHTML = '';
    const label = document.createElement('span');
    label.style.fontSize = '11px';
    label.style.color = 'var(--text-dim)';
    label.textContent = 'Удалить файл? ';
    actions.appendChild(label);

    const yes = document.createElement('button');
    yes.className = 'haction confirm-yes';
    yes.textContent = 'Да';
    yes.addEventListener('click', async () => {
      const data = await call('delete_file', item.filename);
      if (data.ok) {
        row.remove();
        if (!historyList.children.length) historyEmpty.style.display = 'flex';
      } else {
        errNote.textContent = data.error || 'Не удалось удалить файл';
      }
      resumeHistoryPolling();
    });
    actions.appendChild(yes);

    const cancel = document.createElement('button');
    cancel.className = 'haction confirm-cancel';
    cancel.textContent = 'Отмена';
    cancel.addEventListener('click', () => {
      actions.innerHTML = '';
      actions.appendChild(folder);
      actions.appendChild(remove);
      resumeHistoryPolling();
    });
    actions.appendChild(cancel);
  });
  actions.appendChild(remove);

  row.appendChild(actions);
  return row;
}

async function loadHistory() {
  const data = await call('get_history');
  if (!data.ok) {
    historyList.innerHTML = '';
    const note = document.createElement('div');
    note.id = 'historyLoadError';
    note.textContent = 'Не удалось получить список загрузок';
    historyList.appendChild(note);
    return;
  }

  historyList.innerHTML = '';
  const items = data.items || [];
  historyEmpty.style.display = items.length ? 'none' : 'flex';

  items.forEach((item) => {
    let row;
    if (item.kind === 'active') row = buildActiveRow(item);
    else if (item.kind === 'cancelled') row = buildCancelledRow(item);
    else row = buildDoneRow(item);
    historyList.appendChild(row);
  });
}

/* ---------- настройки: папка загрузок ---------- */

const dirPath = document.getElementById('dirPath');
const dirNote = document.getElementById('dirNote');
const browseBtn = document.getElementById('browseBtn');

browseBtn.addEventListener('click', async () => {
  const data = await call('choose_download_dir');
  if (!data.ok) {
    dirNote.textContent = data.error || 'Не удалось сменить папку';
    return;
  }
  if (data.cancelled) return;
  dirNote.textContent = '';
  dirPath.value = data.download_dir;
});

/* ---------- настройки: автообновление ---------- */

const autoUpdateToggle = document.getElementById('autoUpdateToggle');
autoUpdateToggle.addEventListener('click', async () => {
  const enabled = autoUpdateToggle.getAttribute('aria-pressed') !== 'true';
  const data = await call('set_auto_update', enabled);
  if (!data.ok) return;
  autoUpdateToggle.setAttribute('aria-pressed', data.auto_update ? 'true' : 'false');
  if (data.auto_update) watchUpdate();
  else updateBanner.style.display = 'none';
});

/* ---------- запуск ---------- */

setFormState('idle');

btn.addEventListener('click', startDownload);
stopBtn.addEventListener('click', stopDownload);
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') startDownload();
});

/* ---------- старт: состояние из Python ---------- */

const qualityPills = document.getElementById('qualityPills');
let booted = false;

async function boot() {
  if (booted) return;
  booted = true;

  const data = await call('bootstrap');
  document.body.classList.remove('booting');
  if (!data.ok) {
    showError(data.error, data.error_detail);
    return;
  }

  data.quality_options.forEach((opt) => {
    const option = document.createElement('option');
    option.value = String(opt.height);
    option.textContent = opt.label;
    option.selected = opt.height === data.selected_height;
    quality.appendChild(option);

    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'pill' + (opt.height === data.selected_height ? ' active' : '');
    pill.dataset.height = String(opt.height);
    pill.textContent = opt.height + 'p';
    pill.addEventListener('click', () => applyQuality(pill.dataset.height));
    qualityPills.appendChild(pill);
  });

  document.getElementById('ffmpegBanner').hidden = data.ffmpeg_available;
  dirPath.value = data.download_dir;
  autoUpdateToggle.setAttribute('aria-pressed', data.auto_update ? 'true' : 'false');
  document.getElementById('settingsFoot').textContent =
    (data.ffmpeg_available ? 'ffmpeg найден.' : 'ffmpeg не найден.') +
    ' Версия ' + data.version + '.' +
    (data.max_filesize ? ' Лимит на файл — ' + data.max_filesize + '.' : '');

  watchUpdate();
}

// Мост pywebview наполняется после загрузки страницы и сообщает об этом
// событием pywebviewready. Если скрипт выполнился позже — мост уже готов.
if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.bootstrap === 'function') {
  boot();
} else {
  window.addEventListener('pywebviewready', boot);
}
