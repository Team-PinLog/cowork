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
const previewSection = document.querySelector('#preview-section');
const previewList = document.querySelector('#preview-list');
const editButton = document.querySelector('#edit-button');
const confirmButton = document.querySelector('#confirm-button');
const sprintSelect = document.querySelector('#sprint-select');
const previewSprintName = document.querySelector('#preview-sprint-name');
const previewAssigneeName = document.querySelector('#preview-assignee-name');
const previewRoleTag = document.querySelector('#preview-role-tag');

let csrfToken = '';
let creating = false;
let pendingConfirmation = null;
const receipts = [];
const pendingStorageKey = 'cowork_pending_request';

function loadPendingRequest() {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingStorageKey));
    if (
      typeof value?.text === 'string'
      && typeof value?.key === 'string'
      && Number.isInteger(value?.sprintId)
    ) return value;
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
  loadActiveSprints();
}

async function loadActiveSprints() {
  sprintSelect.disabled = true;
  createButton.disabled = true;
  sprintSelect.replaceChildren(new Option('불러오는 중...', ''));
  try {
    const result = await jsonFetch('/api/sprints');
    sprintSelect.replaceChildren(new Option('활성 스프린트를 선택해주세요', ''));
    for (const sprint of result.sprints || []) {
      sprintSelect.append(new Option(sprint.name, String(sprint.id)));
    }
    if (!result.sprints?.length) {
      sprintSelect.replaceChildren(new Option('활성 스프린트가 없습니다', ''));
      createError.textContent = '활성 스프린트가 없어서 티켓을 만들 수 없어요';
      createError.hidden = false;
      return;
    }
    sprintSelect.disabled = false;
  } catch (error) {
    sprintSelect.replaceChildren(new Option('불러오지 못했습니다', ''));
    createError.textContent = error.message;
    createError.hidden = false;
  }
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
    pendingConfirmation = null;
    hidePreview();
    todoInput.disabled = false;
    sprintSelect.disabled = true;
    sprintSelect.replaceChildren(new Option('불러오는 중...', ''));
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

function hidePreview() {
  previewSection.hidden = true;
  previewList.replaceChildren();
  previewSprintName.textContent = '';
  previewAssigneeName.textContent = '';
  previewRoleTag.textContent = '';
}

function showPreview(submissionId, sentText, sprint, assignee, tasks) {
  previewList.replaceChildren();
  for (const task of tasks) {
    const row = document.createElement('li');
    const summary = document.createElement('strong');
    summary.textContent = task.summary;
    row.append(summary);
    if (task.description) {
      const description = document.createElement('p');
      description.textContent = task.description;
      row.append(description);
    }
    previewList.append(row);
  }
  pendingConfirmation = {submissionId, sentText};
  previewSprintName.textContent = sprint?.name || '';
  previewAssigneeName.textContent = assignee?.display_name || '';
  previewRoleTag.textContent = assignee?.role_tag || '';
  previewSection.hidden = false;
  todoInput.disabled = true;
  sprintSelect.disabled = true;
  createButton.disabled = true;
  creating = false;
  createButton.textContent = '티켓 만들기';
  progress.textContent = '';
}

function finishCreation() {
  creating = false;
  pendingConfirmation = null;
  hidePreview();
  todoInput.disabled = false;
  sprintSelect.disabled = false;
  createButton.disabled = !sprintSelect.value;
  createButton.textContent = '티켓 만들기';
  confirmButton.disabled = false;
  confirmButton.textContent = '확인하고 만들기';
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
    if (result.state === 'review') {
      showPreview(
        submissionId,
        sentText,
        result.sprint,
        result.assignee,
        result.preview || [],
      );
      return;
    }
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

editButton.addEventListener('click', () => {
  pendingConfirmation = null;
  hidePreview();
  todoInput.disabled = false;
  sprintSelect.disabled = false;
  createButton.disabled = !sprintSelect.value;
  progress.textContent = '';
  todoInput.focus();
});

confirmButton.addEventListener('click', async () => {
  if (creating || !pendingConfirmation) return;
  const pending = pendingConfirmation;
  creating = true;
  createError.hidden = true;
  editButton.disabled = true;
  confirmButton.disabled = true;
  confirmButton.textContent = '만드는 중';
  progress.textContent = '티켓 만드는 중';
  try {
    await jsonFetch(`/api/submissions/${pending.submissionId}/confirm`, {
      method: 'POST',
      headers: {'X-CSRF-Token': csrfToken},
    });
    previewSection.hidden = true;
    editButton.disabled = false;
    await pollSubmission(pending.submissionId, pending.sentText);
  } catch (error) {
    createError.textContent = error.message;
    createError.hidden = false;
    creating = false;
    editButton.disabled = false;
    confirmButton.disabled = false;
    confirmButton.textContent = '확인하고 만들기';
    progress.textContent = '';
  }
});

createButton.addEventListener('click', async () => {
  if (creating) return;
  const sentText = todoInput.value;
  const sprintId = Number(sprintSelect.value);
  if (!sentText.trim() || !Number.isInteger(sprintId) || sprintId <= 0) return;
  creating = true;
  hidePreview();
  createError.hidden = true;
  sprintSelect.disabled = true;
  createButton.disabled = true;
  createButton.textContent = '정리 중';
  progress.textContent = '할 일 정리하는 중';
  const previous = loadPendingRequest();
  const attempt = previous?.text === sentText && previous?.sprintId === sprintId
    ? previous
    : {text: sentText, sprintId, key: crypto.randomUUID()};
  savePendingRequest(attempt);
  try {
    const result = await jsonFetch('/api/submissions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken},
      body: JSON.stringify({
        text: sentText,
        sprint_id: sprintId,
        idempotency_key: attempt.key,
      }),
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

sprintSelect.addEventListener('change', () => {
  createButton.disabled = !sprintSelect.value;
});

boot();
