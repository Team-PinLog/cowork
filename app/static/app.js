const loginScreen = document.querySelector('#login-screen');
const appScreen = document.querySelector('#app-screen');
const loginForm = document.querySelector('#login-form');
const loginError = document.querySelector('#login-error');
const accountButton = document.querySelector('#account-button');
const logoutButton = document.querySelector('#logout-button');
const todoInput = document.querySelector('#todo-input');
const createButton = document.querySelector('#create-button');
const progress = document.querySelector('#progress');
const createError = document.querySelector('#create-error');
const receiptSection = document.querySelector('#receipt-section');
const ticketList = document.querySelector('#ticket-list');

let csrfToken = '';
let creating = false;
const receipts = [];
const pendingStorageKey = 'cowork_pending_request';

function loadPendingRequest() {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingStorageKey));
    if (typeof value?.text === 'string' && typeof value?.key === 'string') return value;
  } catch (_) { /* discard invalid browser state */ }
  return null;
}

function savePendingRequest(value) {
  sessionStorage.setItem(pendingStorageKey, JSON.stringify(value));
}

function clearPendingRequest() {
  sessionStorage.removeItem(pendingStorageKey);
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  let body = null;
  try { body = await response.json(); } catch (_) { body = null; }
  if (!response.ok) {
    const error = new Error(body?.detail || '요청을 처리하지 못했어요');
    error.status = response.status;
    throw error;
  }
  return body;
}

function showLogin() {
  loginScreen.hidden = false;
  appScreen.hidden = true;
}

function showApp(me) {
  csrfToken = me.csrf_token;
  accountButton.textContent = me.display_name;
  loginScreen.hidden = true;
  appScreen.hidden = false;
}

async function boot() {
  try {
    const me = await jsonFetch('/api/me');
    if (me.authenticated) showApp(me); else showLogin();
  } catch (_) {
    showLogin();
  }
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  try {
    await jsonFetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        email: document.querySelector('#email').value,
        password: document.querySelector('#password').value,
      }),
    });
    const me = await jsonFetch('/api/me');
    showApp(me);
    loginForm.reset();
  } catch (error) {
    loginError.textContent = error.message;
    loginError.hidden = false;
  }
});

accountButton.addEventListener('click', () => {
  logoutButton.hidden = !logoutButton.hidden;
  accountButton.setAttribute('aria-expanded', String(!logoutButton.hidden));
});

logoutButton.addEventListener('click', async () => {
  try {
    await fetch('/api/logout', {method: 'POST', headers: {'X-CSRF-Token': csrfToken}});
  } finally {
    csrfToken = '';
    receipts.length = 0;
    renderReceipts();
    showLogin();
  }
});

function renderReceipts() {
  ticketList.replaceChildren();
  receiptSection.hidden = receipts.length === 0;
  for (const ticket of receipts) {
    const row = document.createElement('li');
    const key = document.createElement('a');
    key.className = 'ticket-key';
    key.href = ticket.url;
    key.target = '_blank';
    key.rel = 'noopener noreferrer';
    key.textContent = ticket.issue_key;
    const summary = document.createElement('span');
    summary.className = 'ticket-summary';
    summary.textContent = ticket.summary;
    const external = document.createElement('span');
    external.className = 'external';
    external.setAttribute('aria-hidden', 'true');
    external.textContent = '↗';
    row.append(key, summary, external);
    ticketList.append(row);
  }
}

function finishCreation() {
  creating = false;
  createButton.disabled = false;
  createButton.textContent = '티켓 만들기';
  progress.textContent = '';
}

async function pollSubmission(submissionId, sentText) {
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    let result;
    try {
      result = await jsonFetch(`/api/submissions/${submissionId}`);
    } catch (_) {
      createError.textContent = '연결에 문제가 있어요. 다시 시도해주세요';
      createError.hidden = false;
      finishCreation();
      return;
    }
    if (result.progress) progress.textContent = result.progress;
    if (['received', 'organizing', 'creating'].includes(result.state)) continue;
    if (result.tickets?.length) {
      receipts.unshift(...result.tickets.slice().reverse());
      renderReceipts();
    }
    if (result.state === 'completed' || result.state === 'partial') {
      if (todoInput.value === sentText) todoInput.value = '';
      clearPendingRequest();
    } else if (result.retryable) {
      clearPendingRequest();
    }
    if (result.message) {
      createError.textContent = result.message;
      createError.hidden = false;
    }
    finishCreation();
    return;
  }
}

createButton.addEventListener('click', async () => {
  if (creating) return;
  const sentText = todoInput.value;
  if (!sentText.trim()) return;
  creating = true;
  createError.hidden = true;
  createButton.disabled = true;
  createButton.textContent = '만드는 중';
  progress.textContent = '할 일 정리하는 중';
  const previous = loadPendingRequest();
  const attempt = previous?.text === sentText
    ? previous
    : {text: sentText, key: crypto.randomUUID()};
  savePendingRequest(attempt);
  try {
    const result = await jsonFetch('/api/submissions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken},
      body: JSON.stringify({text: sentText, idempotency_key: attempt.key}),
    });
    await pollSubmission(result.submission_id, sentText);
  } catch (error) {
    createError.textContent = error.message === '요청을 처리하지 못했어요'
      ? '연결에 문제가 있어요. 다시 시도해주세요'
      : error.message;
    createError.hidden = false;
    finishCreation();
  }
});

boot();
