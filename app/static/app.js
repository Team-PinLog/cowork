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
const addTicketButton = document.querySelector('#add-ticket-button');
const sprintSelect = document.querySelector('#sprint-select');
const previewSprintName = document.querySelector('#preview-sprint-name');
const previewAssigneeName = document.querySelector('#preview-assignee-name');
const previewRoleTag = document.querySelector('#preview-role-tag');
const copyGuideButton = document.querySelector('#copy-guide-button');
const aiGuidePrompt = document.querySelector('#ai-guide-prompt');
const copyGuideStatus = document.querySelector('#copy-guide-status');

let csrfToken = '';
let creating = false;
let editingPreview = false;
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

function setProgress(message = '', loading = false) {
  progress.textContent = message;
  progress.classList.toggle('loading', loading && Boolean(message));
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
  setProgress('스프린트 불러오는 중', true);
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
      setProgress();
      return;
    }
    sprintSelect.disabled = false;
    setProgress();
  } catch (error) {
    sprintSelect.replaceChildren(new Option('불러오지 못했습니다', ''));
    createError.textContent = error.message;
    createError.hidden = false;
    setProgress();
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

copyGuideButton.addEventListener('click', async () => {
  const guide = aiGuidePrompt.textContent.trim();
  try {
    await navigator.clipboard.writeText(guide);
    copyGuideButton.textContent = '복사 완료';
    copyGuideStatus.textContent = 'AI에게 전달할 가이드를 복사했습니다.';
    window.setTimeout(() => {
      copyGuideButton.textContent = '가이드 복사';
      copyGuideStatus.textContent = '';
    }, 2500);
  } catch (_) {
    copyGuideStatus.textContent = '복사하지 못했습니다. 가이드 내용을 직접 선택해 복사해주세요.';
  }
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
  addTicketButton.hidden = true;
}

function descriptionBody(description) {
  return (description || '').replace(/^##\s*작업 내용\s*/, '').trim();
}

function summaryBody(summary) {
  return (summary || '').replace(/^\s*\[(?:FE|BE|Infra|AI)\]\s*/i, '').trim();
}

function updateEditorLabels() {
  [...previewList.children].forEach((row, index) => {
    row.querySelector('.preview-summary-input')?.setAttribute('aria-label', `${index + 1}번 티켓 제목`);
    row.querySelector('.preview-description-input')?.setAttribute('aria-label', `${index + 1}번 티켓 설명`);
    row.querySelector('.delete-ticket-button')?.setAttribute('aria-label', `${index + 1}번 티켓 삭제`);
  });
}

function draftTasksFromEditor() {
  const summaries = [...previewList.querySelectorAll('.preview-summary-input')];
  const descriptions = [...previewList.querySelectorAll('.preview-description-input')];
  return summaries.map((summary, index) => ({
    summary: summary.value.trim(),
    description: descriptions[index].value.trim() || null,
  }));
}

function renderPreviewTasks(tasks, editing = false) {
  previewList.replaceChildren();
  tasks.forEach((task, index) => {
    const row = document.createElement('li');
    if (editing) {
      const heading = document.createElement('div');
      heading.className = 'preview-ticket-editor-heading';
      const summary = document.createElement('input');
      summary.className = 'preview-summary-input';
      summary.value = summaryBody(task.summary);
      summary.maxLength = 255;
      summary.required = true;
      const description = document.createElement('textarea');
      description.className = 'preview-description-input';
      description.value = descriptionBody(task.description);
      description.maxLength = 5000;
      const deleteButton = document.createElement('button');
      deleteButton.className = 'delete-ticket-button';
      deleteButton.type = 'button';
      deleteButton.textContent = '티켓 삭제';
      deleteButton.addEventListener('click', () => {
        if (previewList.children.length <= 1) {
          createError.textContent = '티켓은 최소 1개가 필요합니다';
          createError.hidden = false;
          return;
        }
        row.remove();
        createError.hidden = true;
        updateEditorLabels();
      });
      heading.append(summary, deleteButton);
      row.append(heading, description);
    } else {
      const summary = document.createElement('strong');
      summary.textContent = task.summary;
      row.append(summary);
    }
    if (!editing && task.description) {
      const description = document.createElement('p');
      description.textContent = task.description;
      row.append(description);
    }
    previewList.append(row);
  });
  if (editing) updateEditorLabels();
}

function showPreview(submissionId, sentText, sprint, assignee, tasks) {
  renderPreviewTasks(tasks);
  pendingConfirmation = {submissionId, sentText, sprint, assignee, tasks};
  editingPreview = false;
  editButton.textContent = '수정하기';
  confirmButton.disabled = false;
  addTicketButton.hidden = true;
  previewSprintName.textContent = sprint?.name || '';
  previewAssigneeName.textContent = assignee?.display_name || '';
  previewRoleTag.textContent = assignee?.role_tag || '';
  previewSection.hidden = false;
  todoInput.disabled = true;
  sprintSelect.disabled = true;
  createButton.disabled = true;
  creating = false;
  createButton.textContent = '티켓 만들기';
  setProgress();
}

function finishCreation() {
  creating = false;
  editingPreview = false;
  pendingConfirmation = null;
  hidePreview();
  todoInput.disabled = false;
  sprintSelect.disabled = false;
  createButton.disabled = !sprintSelect.value;
  createButton.textContent = '티켓 만들기';
  confirmButton.disabled = false;
  confirmButton.textContent = '확인하고 만들기';
  setProgress();
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
    if (result.progress) setProgress(result.progress, true);
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

editButton.addEventListener('click', async () => {
  if (!pendingConfirmation || creating) return;
  if (!editingPreview) {
    editingPreview = true;
    renderPreviewTasks(pendingConfirmation.tasks, true);
    editButton.textContent = '수정 완료';
    confirmButton.disabled = true;
    addTicketButton.hidden = false;
    previewList.querySelector('input')?.focus();
    return;
  }
  const tasks = draftTasksFromEditor();
  if (tasks.some((task) => !task.summary)) {
    createError.textContent = '모든 티켓의 제목을 입력해주세요';
    createError.hidden = false;
    return;
  }
  editButton.disabled = true;
  createError.hidden = true;
  setProgress('수정 내용 저장 중', true);
  try {
    const result = await jsonFetch(
      `/api/submissions/${pendingConfirmation.submissionId}/draft`,
      {
        method: 'PUT',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken},
        body: JSON.stringify({tasks}),
      },
    );
    pendingConfirmation.tasks = result.preview;
    renderPreviewTasks(result.preview);
    editingPreview = false;
    editButton.textContent = '수정하기';
    confirmButton.disabled = false;
    addTicketButton.hidden = true;
  } catch (error) {
    createError.textContent = error.message;
    createError.hidden = false;
  } finally {
    editButton.disabled = false;
    setProgress();
  }
});

addTicketButton.addEventListener('click', () => {
  if (!editingPreview || creating) return;
  const tasks = draftTasksFromEditor();
  if (tasks.length >= 20) {
    createError.textContent = '티켓은 최대 20개까지 만들 수 있습니다';
    createError.hidden = false;
    return;
  }
  tasks.push({summary: '', description: null});
  renderPreviewTasks(tasks, true);
  createError.hidden = true;
  previewList.querySelector('li:last-child .preview-summary-input')?.focus();
});

confirmButton.addEventListener('click', async () => {
  if (creating || editingPreview || !pendingConfirmation) return;
  const pending = pendingConfirmation;
  creating = true;
  createError.hidden = true;
  editButton.disabled = true;
  confirmButton.disabled = true;
  confirmButton.textContent = '만드는 중';
  setProgress('티켓 만드는 중', true);
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
    setProgress();
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
  setProgress('할 일 정리하는 중', true);
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
