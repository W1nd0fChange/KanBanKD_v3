const COMPLEXITY = ["легкое", "среднее", "сложное"];
const TASK_TYPES = ["Предложение", "ТЭО", "ЗИП", "ЗПКД", "Точный"];
const DIRECTORATES = [
  "D1 CASUAL",
  "D10 HOME",
  "D11 UNDE",
  "D2 SPORT",
  "D3 FORMA",
  "D4 DENIM",
  "D5 OUTER",
  "D6 SHOES",
  "D7 ACC",
  "D8 KIDS",
  "D9 Q-LINE",
];
const NUMBER_META = [
  ["bp_number", "Номер БП"],
  ["teo_number", "Номер ТЭО"],
  ["zip_number", "Номер ЗИП"],
  ["zpkd_number", "Номер заявки на производство"],
  ["exact_number", "Номер точного"],
];
const STATUS_CHOICES = [
  ["work", "В работе"],
  ["Выполняется", "Выполняется"],
  ["Пауза", "Пауза"],
  ["Выполнено", "Выполнено"],
  ["Отменено", "Отменено"],
];
const RANK = { "Создано": 0, "Назначен отв.": 1, "Выполняется": 0, "Пауза": 1, "Выполнено": 2, "Отменено": 3 };
const PALETTE = ["#5b5fc7", "#038387", "#004e8c", "#498205", "#c43e1c", "#881798", "#986f0b", "#4f6bed"];

const boardEl = document.getElementById("board");
const paneEl = document.getElementById("pane");
const scrimEl = document.getElementById("scrim");
const toastEl = document.getElementById("toast");
const dbStateEl = document.getElementById("dbState");

let board = { columns: [], tickets: [] };
let filter = "work";
let boardFilter = "work";
let directorateFilter = "";
let taskTypeFilter = "";
let complexityFilter = "";
let mode = null;
let addingPerson = false;
let suppressClick = false;
let toastTimer = 0;

document.getElementById("statusButton").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleMenu("statusList");
});

document.getElementById("directorateButton").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleMenu("directorateList");
});

document.getElementById("taskTypeButton").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleMenu("taskTypeList");
});

document.getElementById("complexityButton").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleMenu("complexityList");
});

document.getElementById("statusList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-status]");
  if (!button) return;
  boardFilter = button.dataset.status;
  if (filter !== "list") filter = boardFilter;
  closeMenus();
  paintPickers();
  renderBoard();
});

document.getElementById("directorateList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-directorate]");
  if (!button) return;
  directorateFilter = button.dataset.directorate;
  closeMenus();
  paintPickers();
  renderBoard();
});

document.getElementById("taskTypeList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-task-type]");
  if (!button) return;
  taskTypeFilter = button.dataset.taskType;
  closeMenus();
  paintPickers();
  renderBoard();
});

document.getElementById("complexityList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-complexity]");
  if (!button) return;
  complexityFilter = button.dataset.complexity;
  closeMenus();
  paintPickers();
  renderBoard();
});

document.getElementById("doneByDirectorate").addEventListener("click", () => {
  if (filter === "list") filter = boardFilter;
  else {
    boardFilter = filter;
    filter = "list";
  }
  closeMenus();
  paintPickers();
  renderBoard();
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".menu")) closeMenus();
});

scrimEl.addEventListener("click", closePane);

function toggleMenu(id) {
  const list = document.getElementById(id);
  const willOpen = list.hidden;
  closeMenus();
  list.hidden = !willOpen;
}

function closeMenus() {
  document.getElementById("statusList").hidden = true;
  document.getElementById("directorateList").hidden = true;
  document.getElementById("taskTypeList").hidden = true;
  document.getElementById("complexityList").hidden = true;
}

function statusFilter() {
  return filter === "list" ? boardFilter : filter;
}

function paintPickers() {
  const status = STATUS_CHOICES.find(([value]) => value === statusFilter());
  document.getElementById("statusButton").textContent = "Статус: " + (status ? status[1] : "В работе");
  document.getElementById("directorateButton").textContent = "Дирекция: " + (directorateFilter || "все");
  document.getElementById("taskTypeButton").textContent = "Тип: " + (taskTypeFilter || "все");
  document.getElementById("complexityButton").textContent = "Сложность: " + (complexityFilter || "все");
  document.getElementById("doneByDirectorate").classList.toggle("is-on", filter === "list");
  for (const button of document.querySelectorAll("[data-status]")) {
    button.classList.toggle("is-on", button.dataset.status === statusFilter());
  }
  for (const button of document.querySelectorAll("[data-directorate]")) {
    button.classList.toggle("is-on", button.dataset.directorate === directorateFilter);
  }
  for (const button of document.querySelectorAll("[data-task-type]")) {
    button.classList.toggle("is-on", button.dataset.taskType === taskTypeFilter);
  }
  for (const button of document.querySelectorAll("[data-complexity]")) {
    button.classList.toggle("is-on", button.dataset.complexity === complexityFilter);
  }
}

function fillDirectorates() {
  document.getElementById("directorateList").insertAdjacentHTML("beforeend", DIRECTORATES.map((item) => (
    '<button type="button" data-directorate="' + esc(item) + '">' + esc(item) + "</button>"
  )).join(""));
}

function fillTaskTypes() {
  document.getElementById("taskTypeList").insertAdjacentHTML("beforeend", TASK_TYPES.map((item) => (
    '<button type="button" data-task-type="' + esc(item) + '">' + esc(item) + "</button>"
  )).join(""));
}

function fillComplexity() {
  document.getElementById("complexityList").insertAdjacentHTML("beforeend", COMPLEXITY.map((item) => (
    '<button type="button" data-complexity="' + esc(item) + '">' + esc(item) + "</button>"
  )).join(""));
}

async function showShare() {
  const box = document.getElementById("share");
  const link = document.getElementById("shareLink");
  try {
    const data = await api("/api/share");
    const url = (data.urls || [])[0];
    if (!url) {
      box.hidden = true;
      return;
    }
    link.href = url;
    link.textContent = url;
    box.hidden = false;
  } catch (error) {
    box.hidden = true;
  }
}

async function boot() {
  fillDirectorates();
  fillTaskTypes();
  fillComplexity();
  paintPickers();
  showShare();
  try {
    await refresh();
  } catch (error) {
    toast(error.message);
  }
  probeDb();
}

async function probeDb() {
  try {
    const health = await api("/api/health");
    dbStateEl.classList.remove("is-ok", "is-bad");
    if (!health.enabled) {
      dbStateEl.querySelector(".db-label").textContent = "База выключена";
      return;
    }
    const schemaHint = health.schema
      ? `\nСхема: ${health.schema.tag}\n${health.schema.module_file}`
      : "";
    if (!health.ticket_actions?.includes("pause")) {
      dbStateEl.classList.add("is-bad");
      dbStateEl.querySelector(".db-label").textContent = "Старый API";
      dbStateEl.title = "Сервер без pause/resume. stop.bat → run.bat, затем Ctrl+F5." + schemaHint;
      toast("Перезапустите канбан: нет API pause/resume");
      return;
    }
    if (health.schema?.legacy_column_names) {
      dbStateEl.classList.add("is-bad");
      dbStateEl.querySelector(".db-label").textContent = "Старый db.py";
      dbStateEl.title = "На сервере устаревшие имена колонок SQL. Перезапустите run.bat из актуальной папки." + schemaHint;
      toast("Сервер отдаёт старый db.py. Закройте stop.bat и снова run.bat.");
      return;
    }
    if (health.db) {
      dbStateEl.classList.add("is-ok");
      dbStateEl.querySelector(".db-label").textContent = "DGDWH";
      dbStateEl.title = "Запись тикетов в DGDWH доступна" + schemaHint;
    } else {
      dbStateEl.classList.add("is-bad");
      dbStateEl.querySelector(".db-label").textContent = "Только локально";
      dbStateEl.title = (health.error || "Нет связи с DGDWH") + schemaHint;
    }
  } catch (error) {
    dbStateEl.classList.add("is-bad");
    dbStateEl.querySelector(".db-label").textContent = "Только локально";
    dbStateEl.title = error.message;
  }
}

function noteDb(result) {
  if (!result) return;
  const dbResult = result.db !== undefined ? result.db : result;
  const pauseDb = result.pause_db;
  if (pauseDb && pauseDb.saved === false && pauseDb.error) {
    toast("Запись паузы в БД: " + pauseDb.error);
  }
  if (pauseDb && pauseDb.saved && dbResult?.saved === false && dbResult.error) {
    toast("Пауза в БД записана. Статус в commercial: " + dbResult.error);
    dbStateEl.classList.remove("is-ok");
    dbStateEl.classList.add("is-bad");
    dbStateEl.querySelector(".db-label").textContent = "Частично";
    return;
  }
  if (!dbResult || dbResult.skipped || dbResult.saved !== false || !dbResult.error) return;
  toast("На доске сохранено. В commercial не записалось: " + dbResult.error);
  dbStateEl.classList.remove("is-ok");
  dbStateEl.classList.add("is-bad");
  dbStateEl.querySelector(".db-label").textContent = "Только локально";
}

async function refresh() {
  board = await api("/api/board");
  renderBoard();
  if (mode === "create") renderPane();
  else if (mode) {
    const ticket = board.tickets.find((item) => item.id === mode);
    if (!ticket) closePane();
    else renderPane();
  }
}

function renderBoard() {
  if (filter === "list") {
    const tickets = visible(board.tickets);
    boardEl.innerHTML = `
      <section class="zone zone-done">
        <div class="zone-label">Все задачи</div>
        ${columnHtml({
          id: "task-list",
          title: "Список",
          count: tickets.length,
          tickets,
        })}
      </section>
    `;
    bindBoard();
    return;
  }
  const intake = visible(board.tickets.filter((item) => !item.column_id));
  const people = board.columns
    .filter((column) => !column.hidden)
    .map((column) => ({
      ...column,
      tickets: sortEmployeeTickets(
        visible(board.tickets.filter((item) => item.column_id === column.id)),
      ),
    }));

  boardEl.innerHTML = `
    <section class="zone zone-intake">
      <div class="zone-label">Внос в проработку</div>
      ${columnHtml({
        id: "inbox",
        title: "К проработке",
        count: intake.length,
        tickets: intake,
        inbox: true,
      })}
    </section>
    <section class="zone zone-team">
      <div class="zone-head">
        <div class="zone-label">Сотрудники</div>
        ${personControl()}
      </div>
      ${hiddenBar()}
      <div class="zone-columns">
        ${people.map((column) => columnHtml({
          id: column.id,
          title: column.name,
          count: column.tickets.length,
          tickets: column.tickets,
          person: true,
        })).join("")}
      </div>
    </section>
  `;
  bindBoard();
}

function columnHtml({ id, title, count, tickets, inbox, person }) {
  const cards = tickets.length
    ? tickets.map(cardHtml).join("")
    : `<div class="empty-hint">${emptyHint(inbox)}</div>`;
  const head = person
    ? `<span class="avatar" style="background:${colorFor(title)}">${esc(initials(title))}</span>
       <span class="column-name">${esc(title)}</span>
       <span class="column-count">${count}</span>
       <button class="text-btn" type="button" data-hide-column="${esc(id)}">Скрыть</button>`
    : `<span class="column-name">${esc(title)}</span><span class="column-count">${count}</span>`;
  const add = inbox && filter !== "list"
    ? `<button class="add-task" type="button" data-create>+ Добавить задачу</button>`
    : "";
  return `
    <div class="column" data-column="${esc(id)}">
      <div class="column-head">${head}</div>
      ${add}
      <div class="cards">${cards}</div>
    </div>
  `;
}

function emptyHint(inbox) {
  if (filter === "list") return "Нет задач по выбранным фильтрам.";
  return inbox
    ? "Новые карточки приходят без номеров. Карточку перетаскивают сотруднику."
    : "Перетащите сюда задачу из колонки «К проработке».";
}

function hiddenBar() {
  const hidden = board.columns.filter((column) => column.hidden);
  if (!hidden.length) return "";
  const buttons = hidden.map((column) => (
    '<button class="text-btn" type="button" data-show-column="' + esc(column.id) + '">' +
    esc(column.name) + " · показать</button>"
  )).join("");
  return '<div class="hidden-list"><span>Скрытые сотрудники</span>' + buttons + "</div>";
}

function personControl() {
  if (addingPerson) {
    return `
      <span class="person-add">
        <input class="name-input" id="personName" placeholder="ФИО сотрудника" maxlength="120">
        <button class="text-btn ok" type="button" id="personSave">Добавить</button>
        <button class="text-btn" type="button" id="personCancel">Отмена</button>
      </span>
    `;
  }
  return `<button class="add-person" type="button" id="personAdd">+ Сотрудник</button>`;
}

function employeeRank(status) {
  if (status === "Выполняется") return 0;
  if (status === "Пауза") return 1;
  return 2;
}

function sortEmployeeTickets(tickets) {
  return tickets.slice().sort((a, b) => {
    const byRank = employeeRank(a.status) - employeeRank(b.status);
    if (byRank !== 0) return byRank;
    return (a.created_at || "").localeCompare(b.created_at || "");
  });
}

function cardHtml(ticket) {
  const terminal = ticket.status === "Выполнено" || ticket.status === "Отменено";
  const executing = ticket.status === "Выполняется";
  const paused = ticket.status === "Пауза";
  const klass = ticket.status === "Выполнено"
    ? "is-done"
    : ticket.status === "Отменено"
      ? "is-cancel"
      : executing
        ? "is-executing"
        : paused
          ? "is-paused"
          : "";
  const note = ticket.comment || (ticket.lead_comment ? "Лид: " + ticket.lead_comment : "");
  const docs = NUMBER_META
    .filter(([key]) => ticket[key] && !(ticket.status === "Выполнено" && ticket.document_number && ticket[key] === ticket.document_number))
    .map(([key, label]) => label + " " + ticket[key]);
  const closeDoc = ticket.status === "Выполнено" && ticket.document_number
    ? `<span class="card-doc">Номер документа: ${esc(ticket.document_number)}</span>`
    : "";
  const file = ticket.file_name
    ? `<span class="file-chip"><svg class="clip" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M10.8 1.5a3.2 3.2 0 0 1 0 4.5L6.2 10.6a2.1 2.1 0 0 1-3-3l4.2-4.2.8.8-4.2 4.2a1 1 0 1 0 1.4 1.4l4.6-4.6a2 2 0 0 0-2.8-2.8L2.6 7a3.2 3.2 0 0 0 4.5 4.5l5.2-5.2.8.8-5.2 5.2a4.3 4.3 0 0 1-6.1-6.1l4.6-4.6a3.2 3.2 0 0 1 4.4-.1z"/></svg>${esc(ticket.file_name)}</span>`
    : "";
  let workActions = "";
  if (ticket.column_id && !terminal) {
    if (executing) {
      workActions =
        `<button class="text-btn pause" type="button" data-ticket-action="pause" data-ticket-id="${ticket.id}">Пауза</button>` +
        `<button class="text-btn ok" type="button" data-ticket-action="done" data-ticket-id="${ticket.id}">Выполнено</button>`;
    } else if (paused) {
      workActions =
        `<button class="text-btn ok" type="button" data-ticket-action="resume" data-ticket-id="${ticket.id}">Возобновить</button>` +
        `<button class="text-btn ok" type="button" data-ticket-action="done" data-ticket-id="${ticket.id}">Выполнено</button>`;
    } else if (ticket.status === "Назначен отв." && !ticket.work_started_at) {
      workActions = `<button class="text-btn ok" type="button" data-ticket-action="start-work" data-ticket-id="${ticket.id}">Начать выполнение</button>`;
    }
  }
  const actions = terminal ? "" : `
    <div class="card-actions">
      ${workActions}
      <button class="text-btn stop" type="button" data-cancel="${ticket.id}">Отменить</button>
    </div>`;
  return `
    <article class="card ${klass}" draggable="${terminal || ticket.column_id ? "false" : "true"}" data-id="${ticket.id}">
      <div class="card-top">
        <div class="card-title">${esc(ticket.task_type || "Задача")}${ticket.record_id != null && ticket.record_id !== ""
          ? `<span class="card-num"> (Номер тикета — ${esc(ticket.record_id)})</span>`
          : ""}</div>
      </div>
      <div class="card-meta">
        ${closeDoc}
        ${docs.map((item) => `<span>${esc(item)}</span>`).join("")}
        ${ticket.directorate ? `<span>${esc(ticket.directorate)}</span>` : ""}
        ${filter === "list" && ticket.assignee ? `<span>${esc(ticket.assignee)}</span>` : ""}
        <span class="pill ${pillClass(ticket.complexity)}">${esc(ticket.complexity)}</span>
        <span>${ticket.row_count} строк</span>
        ${file}
      </div>
      ${note ? `<div class="card-note">${esc(note)}</div>` : ""}
      ${ticket.cancel_comment ? `<div class="card-note">Отмена: ${esc(ticket.cancel_comment)}</div>` : ""}
      <div class="card-meta"><span class="badge ${badgeClass(ticket.status)}">${esc(ticket.status)}</span></div>
      ${actions}
    </article>
  `;
}

function bindBoard() {
  boardEl.querySelector("[data-create]")?.addEventListener("click", () => openCreate());
  boardEl.querySelector("#personAdd")?.addEventListener("click", () => {
    addingPerson = true;
    renderBoard();
    boardEl.querySelector("#personName")?.focus();
  });
  boardEl.querySelector("#personCancel")?.addEventListener("click", () => {
    addingPerson = false;
    renderBoard();
  });
  boardEl.querySelector("#personSave")?.addEventListener("click", savePerson);
  boardEl.querySelector("#personName")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") savePerson();
    if (event.key === "Escape") {
      addingPerson = false;
      renderBoard();
    }
  });

  for (const button of boardEl.querySelectorAll("[data-hide-column], [data-show-column]")) {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const id = button.dataset.hideColumn || button.dataset.showColumn;
      const action = button.dataset.hideColumn ? "hide" : "show";
      try {
        await api("/api/columns/" + id + "/" + action, { method: "POST" });
        await refresh();
      } catch (error) {
        toast(error.message);
      }
    });
  }

  for (const card of boardEl.querySelectorAll(".card")) {
    card.addEventListener("dragstart", (event) => {
      suppressClick = true;
      card.classList.add("is-dragging");
      event.dataTransfer.setData("text/plain", card.dataset.id);
      event.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("is-dragging");
      setTimeout(() => { suppressClick = false; }, 80);
    });
    card.addEventListener("click", (event) => {
      if (event.target.closest("button") || suppressClick) return;
      openTicket(card.dataset.id);
    });
  }

  for (const button of boardEl.querySelectorAll("[data-ticket-action]")) {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = button.getAttribute("data-ticket-id");
      const action = button.getAttribute("data-ticket-action");
      if (!id) {
        toast("Не удалось определить задачу");
        return;
      }
      if (action === "start-work") markStartWork(id);
      else if (action === "pause") markPause(id);
      else if (action === "resume") markResume(id);
      else if (action === "done") askDone(id);
    });
  }
  for (const button of boardEl.querySelectorAll("[data-cancel]")) {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      askCancel(button.dataset.cancel);
    });
  }

  for (const column of boardEl.querySelectorAll(".column[data-column]")) {
    if (column.dataset.column === "inbox" || column.dataset.column === "task-list") continue;
    column.addEventListener("dragover", (event) => {
      event.preventDefault();
      column.classList.add("is-over");
    });
    column.addEventListener("dragleave", () => column.classList.remove("is-over"));
    column.addEventListener("drop", async (event) => {
      event.preventDefault();
      column.classList.remove("is-over");
      const id = event.dataTransfer.getData("text/plain");
      if (!id) return;
      try {
        const result = await api("/api/tickets/" + id + "/move", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ column_id: column.dataset.column }),
        });
        noteDb(result.db);
        await refresh();
      } catch (error) {
        toast(error.message);
      }
    });
  }
}

async function savePerson() {
  const input = document.getElementById("personName");
  const name = input ? input.value.trim() : "";
  try {
    await api("/api/columns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    addingPerson = false;
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

function openCreate() {
  mode = "create";
  renderPane();
}

function openTicket(id) {
  mode = id;
  renderPane();
}

function closePane() {
  mode = null;
  paneEl.hidden = true;
  scrimEl.hidden = true;
  paneEl.innerHTML = "";
}

function renderPane() {
  const ticket = mode && mode !== "create" ? board.tickets.find((item) => item.id === mode) : null;
  if (mode !== "create" && !ticket) {
    closePane();
    return;
  }
  const creating = mode === "create";
  const value = ticket || {
    task_type: "Предложение",
    directorate: "",
    row_count: "",
    complexity: "легкое",
    comment: "",
    lead_comment: "",
    file_name: "",
    status: "Создано",
    assignee: null,
    column_id: null,
  };
  const viewOnly = !creating;
  const frozen = viewOnly && (value.status === "Выполнено" || value.status === "Отменено");
  const lock = viewOnly ? "disabled" : "";
  const readOnly = viewOnly ? "readonly" : "";
  let numbers = "";
  if (value.status === "Выполнено") {
    numbers = NUMBER_META
      .filter(([key]) => value[key])
      .map(([key, label]) => `<div class="field"><label>${esc(label)}</label><input value="${esc(value[key])}" readonly></div>`)
      .join("");
  }
  const cancelNote = value.cancel_comment
    ? `<div class="field"><label>Комментарий отмены</label><textarea readonly>${esc(value.cancel_comment)}</textarea></div>`
    : "";
  const directorateOptions = '<option value="">Выберите дирекцию</option>' +
    DIRECTORATES.map((item) => (
      '<option value="' + esc(item) + '"' + (item === value.directorate ? " selected" : "") + ">" +
      esc(item) + "</option>"
    )).join("");
  let actions = "";
  if (creating) {
    actions =
      '<button class="primary" type="submit">Проработать</button>' +
      '<button class="ghost" type="button" id="paneDismiss">Отменить</button>';
  } else {
    actions = '<button class="ghost" type="button" id="paneDismiss">Закрыть</button>';
    if (!frozen && value.column_id) {
      if (value.status === "Выполняется") {
        actions += '<button class="ghost" type="button" id="panePause">Пауза</button>';
        actions += '<button class="ghost" type="button" id="paneDone">Выполнено</button>';
      } else if (value.status === "Пауза") {
        actions += '<button class="ghost" type="button" id="paneResume">Возобновить</button>';
        actions += '<button class="ghost" type="button" id="paneDone">Выполнено</button>';
      } else if (value.status === "Назначен отв." && !value.work_started_at) {
        actions += '<button class="ghost" type="button" id="paneStartWork">Начать выполнение</button>';
      } else if (value.work_started_at) {
        actions += '<button class="ghost" type="button" id="paneDone">Выполнено</button>';
      }
    }
  }
  const fileField = creating
    ? `<input id="file" name="file" type="file" accept=".xlsx,.xls,.xlsm,.doc,.docx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword">`
    : ticket?.file_name
      ? `<a class="file-download-btn" href="/files/${esc(ticket.id)}">Скачать прорабатываемый файл</a>`
      : `<span class="file-missing">Файл не прикреплён</span>`;
  paneEl.hidden = false;
  scrimEl.hidden = false;
  paneEl.innerHTML = `
    <div class="pane-head">
      <div class="pane-kicker">${creating ? "Новая задача" : esc(value.assignee || "К проработке")}</div>
      <button class="icon-btn" type="button" id="paneClose" aria-label="Закрыть">×</button>
    </div>
    <form class="pane-body" id="ticketForm">
      <div class="status-line">Статус <span class="badge ${badgeClass(value.status)}">${esc(value.status)}</span></div>
      ${numbers}
      ${cancelNote}
      <div class="field">
        <label for="taskType">Тип задачи</label>
        <select id="taskType" name="task_type" ${lock} ${viewOnly ? 'aria-readonly="true"' : ""}>
          ${TASK_TYPES.map((item) => `<option value="${item}" ${item === value.task_type ? "selected" : ""}>${item}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="directorate">Дирекция</label>
        <select id="directorate" name="directorate" ${creating ? "required" : ""} ${lock}>
          ${directorateOptions}
        </select>
      </div>
      <div class="field">
        <label for="rowCount">Количество строк документа</label>
        <input id="rowCount" name="row_count" inputmode="numeric" ${creating ? "required" : ""} value="${esc(value.row_count)}" placeholder="0" ${lock} ${readOnly}>
      </div>
      <div class="field">
        <label for="complexity">Уровень сложности</label>
        <select id="complexity" name="complexity" ${lock}>
          ${COMPLEXITY.map((item) => `<option value="${item}" ${item === value.complexity ? "selected" : ""}>${item}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>${creating ? "Файл Excel или Word" : "Вложение"}</label>
        <div class="file-row">${fileField}</div>
        ${viewOnly && ticket?.file_name ? `<div class="file-name-hint">${esc(ticket.file_name)}</div>` : ""}
      </div>
      <div class="field">
        <label for="comment">Комментарий</label>
        <textarea id="comment" name="comment" maxlength="500" ${lock} ${readOnly}>${esc(value.comment)}</textarea>
        <span class="counter" data-for="comment"></span>
      </div>
      <div class="field">
        <label for="leadComment">Комментарий лида</label>
        <textarea id="leadComment" name="lead_comment" maxlength="500" ${lock} ${readOnly}>${esc(value.lead_comment)}</textarea>
        <span class="counter" data-for="leadComment"></span>
      </div>
      <div class="form-error" id="formError"></div>
      <div class="pane-actions">
        ${actions}
      </div>
    </form>
  `;
  document.getElementById("paneClose").addEventListener("click", closePane);
  const form = document.getElementById("ticketForm");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!creating) return;
    submitCreate(form);
  });
  document.getElementById("paneDismiss")?.addEventListener("click", closePane);
  document.getElementById("paneStartWork")?.addEventListener("click", () => markStartWork(mode));
  document.getElementById("panePause")?.addEventListener("click", () => markPause(mode));
  document.getElementById("paneResume")?.addEventListener("click", () => markResume(mode));
  document.getElementById("paneDone")?.addEventListener("click", () => askDone(mode));
  for (const area of form.querySelectorAll("textarea")) bindCounter(area);
}

function bindCounter(area) {
  const counter = document.querySelector(`[data-for="${area.id}"]`);
  const paint = () => { counter.textContent = area.value.length + " / 500"; };
  area.addEventListener("input", paint);
  paint();
}

async function submitCreate(form) {
  const error = document.getElementById("formError");
  error.textContent = "";
  try {
    const result = await api("/api/tickets", { method: "POST", body: new FormData(form) });
    noteDb(result.db);
    closePane();
    await refresh();
  } catch (err) {
    error.textContent = err.message;
  }
}

async function submitUpdate(form) {
  const error = document.getElementById("formError");
  error.textContent = "";
  try {
    const result = await api("/api/tickets/" + mode, { method: "PATCH", body: formToUpdate(form) });
    noteDb(result.db);
    await refresh();
  } catch (err) {
    error.textContent = err.message;
  }
}

function formToUpdate(form) {
  const data = new FormData(form);
  const payload = new FormData();
  payload.set("task_type", data.get("task_type") || "");
  payload.set("directorate", data.get("directorate") || "");
  payload.set("row_count", data.get("row_count") || "");
  payload.set("complexity", data.get("complexity") || "");
  payload.set("comment", data.get("comment") || "");
  payload.set("lead_comment", data.get("lead_comment") || "");
  const file = data.get("file");
  if (file && file.size) payload.set("file", file);
  return payload;
}

function askCancel(id, saveForm) {
  const ask = document.getElementById("ask");
  document.getElementById("askComment").value = "";
  document.getElementById("askError").textContent = "";
  ask.dataset.ticketId = id;
  ask.dataset.saveForm = saveForm ? "1" : "";
  ask.hidden = false;
  document.getElementById("askComment").focus();
}

async function markStartWork(id) {
  try {
    const result = await api("/api/tickets/" + id + "/start-work", { method: "POST" });
    noteDb(result);
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

async function markPause(id) {
  try {
    const result = await api("/api/tickets/" + id + "/pause", { method: "POST" });
    noteDb(result);
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

async function markResume(id) {
  try {
    const result = await api("/api/tickets/" + id + "/resume", { method: "POST" });
    noteDb(result);
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

function askDone(id) {
  const ask = document.getElementById("closeAsk");
  document.getElementById("closeNumber").value = "";
  document.getElementById("closeError").textContent = "";
  ask.dataset.ticketId = id;
  ask.hidden = false;
  document.getElementById("closeNumber").focus();
}

function hideClose() {
  const ask = document.getElementById("closeAsk");
  ask.hidden = true;
  ask.dataset.ticketId = "";
}

document.getElementById("closeAbort").addEventListener("click", hideClose);
document.getElementById("closeForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const ask = document.getElementById("closeAsk");
  const error = document.getElementById("closeError");
  error.textContent = "";
  try {
    const result = await api("/api/tickets/" + ask.dataset.ticketId + "/done", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_number: document.getElementById("closeNumber").value }),
    });
    noteDb(result.db);
    hideClose();
    await refresh();
  } catch (err) {
    error.textContent = err.message;
  }
});

function hideAsk() {
  const ask = document.getElementById("ask");
  ask.hidden = true;
  ask.dataset.ticketId = "";
  ask.dataset.saveForm = "";
}

document.getElementById("askAbort").addEventListener("click", hideAsk);
document.getElementById("askForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const ask = document.getElementById("ask");
  const id = ask.dataset.ticketId;
  const error = document.getElementById("askError");
  error.textContent = "";
  try {
    if (ask.dataset.saveForm === "1" && mode === id) {
      const form = document.getElementById("ticketForm");
      const saved = await api("/api/tickets/" + id, { method: "PATCH", body: formToUpdate(form) });
      noteDb(saved.db);
    }
    const result = await api("/api/tickets/" + id + "/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cancel_comment: document.getElementById("askComment").value }),
    });
    noteDb(result.db);
    hideAsk();
    await refresh();
  } catch (err) {
    error.textContent = err.message;
  }
});

function visible(tickets) {
  return tickets
    .filter((item) => {
      const current = statusFilter();
      const byStatus = current === "work"
        ? item.status === "Создано" || item.status === "Назначен отв." || item.status === "Выполняется" || item.status === "Пауза"
        : item.status === current;
      const byDirectorate = !directorateFilter || item.directorate === directorateFilter;
      const byType = !taskTypeFilter || item.task_type === taskTypeFilter;
      const byComplexity = !complexityFilter || item.complexity === complexityFilter;
      return byStatus && byDirectorate && byType && byComplexity;
    })
    .slice()
    .sort((a, b) => (RANK[a.status] - RANK[b.status]) || a.created_at.localeCompare(b.created_at));
}

function pillClass(value) {
  if (value === "легкое") return "easy";
  if (value === "сложное") return "hard";
  return "mid";
}

function badgeClass(status) {
  if (status === "Назначен отв.") return "work";
  if (status === "Выполняется") return "executing";
  if (status === "Пауза") return "paused";
  if (status === "Выполнено") return "done";
  if (status === "Отменено") return "cancel";
  return "";
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
}

function colorFor(name) {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function toast(text) {
  toastEl.textContent = text;
  toastEl.classList.add("is-on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("is-on"), 4200);
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    let message = data.error || "Не удалось выполнить действие";
    if (response.status === 404 && message === "Не найдено" && !data.api_build) {
      message += ". Перезапустите run.bat (старый сервер без маршрута pause)";
    }
    throw new Error(message);
  }
  return data;
}

boot();
