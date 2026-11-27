// Telegram Mini App frontend. Plain ES module, no build step.
// Every piece of content from the API is inserted with textContent; only our own i18n templates
// (which may contain <b>/<i>) go through innerHTML, with their parameters escaped.

const tg = window.Telegram?.WebApp;
const inTelegram = Boolean(tg?.initData);
const root = document.getElementById("app");
const toastEl = document.getElementById("toast");

let TEXTS = {};
let LANGS = {};
let textsLang = null;
let ME = null;
let backHandler = null;

const PRACTICE_PRESETS = [10, 20, 30, 50];
const MEDALS = { 1: "🥇", 2: "🥈", 3: "🥉" };

// ------------------------------------------------------------------ helpers

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Translated template as HTML; parameters are escaped. */
function t(key, params = {}) {
  const template = TEXTS[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (m, k) => (k in params ? esc(params[k]) : m));
}

/** Translated text without markup (for button labels, confirm dialogs). */
function tPlain(key, params = {}) {
  const div = document.createElement("div");
  div.innerHTML = t(key, params);
  return div.textContent;
}

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function render(...nodes) {
  root.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
  window.scrollTo(0, 0);
}

function spinner() {
  return h("div", { class: "center" }, h("div", { class: "spinner", role: "status", "aria-label": "Loading" }));
}

function toast(text, ms = 2200) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (toastEl.hidden = true), ms);
}

function haptic(kind) {
  const hf = tg?.HapticFeedback;
  if (!hf || !tg.isVersionAtLeast?.("6.1")) return;
  if (kind === "light") hf.impactOccurred("light");
  else hf.notificationOccurred(kind);
}

function confirmDialog(text) {
  if (tg?.showConfirm && tg.isVersionAtLeast?.("6.2")) {
    return new Promise((resolve) => tg.showConfirm(text, resolve));
  }
  return Promise.resolve(window.confirm(text));
}

/** Telegram BackButton when inside Telegram, an in-page button otherwise. */
function setBack(fn) {
  if (tg?.BackButton && tg.isVersionAtLeast?.("6.1")) {
    if (backHandler) tg.BackButton.offClick(backHandler);
    backHandler = fn;
    if (fn) { tg.BackButton.onClick(fn); tg.BackButton.show(); } else tg.BackButton.hide();
  } else {
    backHandler = fn;
  }
}

function backLink() {
  if (inTelegram || !backHandler) return null;
  return h("button", { class: "ghost", onclick: backHandler, text: "← " + tPlain("back").replace(/^\S+\s/, "") });
}

function modeLabel(mode) {
  return tPlain(mode === "exam" ? "mode_exam_short" : "mode_practice_short");
}

// ------------------------------------------------------------------ API

class ApiError extends Error {
  constructor(status, detail) { super(detail || String(status)); this.status = status; this.detail = detail; }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (tg?.initData) headers.Authorization = "tma " + tg.initData;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

async function loadTexts(lang) {
  const data = await api(`api/texts/${encodeURIComponent(lang || "uz")}`);
  TEXTS = data.texts;
  LANGS = data.languages;
  textsLang = data.language;
  document.documentElement.lang = textsLang;
}

/** Run a screen; on failure show an error with a retry button. Access errors re-route. */
async function go(screen) {
  try {
    await screen();
  } catch (e) {
    console.error(e);
    if (e instanceof ApiError && e.status === 403) {
      ME = await api("api/me");
      return route();
    }
    if (e instanceof ApiError && e.status === 401) return viewOpenInTelegram();
    render(h("div", { class: "center" },
      h("p", { text: tPlain("web_error") }),
      h("button", { onclick: () => go(screen), text: tPlain("web_retry") }),
    ));
  }
}

// ------------------------------------------------------------------ routing

async function boot() {
  tg?.ready();
  tg?.expand();
  const guess = tg?.initDataUnsafe?.user?.language_code || navigator.language || "uz";
  await loadTexts(guess.slice(0, 2));
  try {
    ME = await api("api/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return viewOpenInTelegram();
    throw e;
  }
  await route();
}

async function route() {
  if (!ME.language) return viewLanguage();
  if (textsLang !== ME.language) await loadTexts(ME.language);
  if (!ME.registered) return viewRegister();
  if (!ME.logged_in) return viewLoggedOut();
  return viewHome();
}

function viewOpenInTelegram() {
  setBack(null);
  render(h("div", { class: "center" }, h("p", { text: tPlain("web_open_in_telegram") })));
}

// ------------------------------------------------------------------ account screens

function viewLanguage() {
  setBack(null);
  render(
    h("h1", { text: tPlain("choose_language") }),
    h("div", { class: "list" },
      Object.entries(LANGS).map(([code, name]) =>
        h("button", {
          class: "tile", text: name,
          onclick: () => go(async () => {
            ME = await api("api/language", { method: "POST", body: { language: code } });
            await route();
          }),
        }))),
  );
}

function viewRegister({ showForm = false } = {}) {
  setBack(null);
  if (!showForm && ME.full_name && ME.group_name && !ME.phone) return viewPhone();

  const name = h("input", { id: "full_name", autocomplete: "name", maxlength: 100, value: ME.full_name || "" });
  const group = h("input", { id: "group_name", maxlength: 50, value: ME.group_name || "" });
  const error = h("div", { class: "error", role: "alert" });
  const save = h("button", { type: "submit", text: tPlain("web_continue") });

  const form = h("form", {
    onsubmit: (ev) => {
      ev.preventDefault();
      save.disabled = true;
      error.textContent = "";
      api("api/register", { method: "POST", body: { full_name: name.value, group_name: group.value } })
        .then(async (me) => {
          ME = me;
          if (ME.registered) { toast(tPlain("reg_done")); await route(); } else viewPhone();
        })
        .catch((e) => {
          save.disabled = false;
          if (e.detail === "invalid_name") { error.innerHTML = t("reg_invalid_name"); name.focus(); }
          else if (e.detail === "invalid_group") { error.innerHTML = t("reg_invalid_group"); group.focus(); }
          else error.textContent = tPlain("web_error");
        });
    },
  },
    h("label", { for: "full_name", text: tPlain("web_name_label") }), name,
    h("label", { for: "group_name", text: tPlain("web_group_label") }), group,
    error, save,
  );
  render(h("p", { class: "pre", html: t("reg_intro") }), h("div", { class: "card" }, form));
}

function viewPhone() {
  setBack(() => viewRegister({ showForm: true }));
  const status = h("p", { class: "hint", role: "status" });
  const share = h("button", { text: tPlain("reg_share_phone") });
  const supported = tg?.requestContact && tg.isVersionAtLeast?.("6.9");

  async function waitForPhone() {
    status.textContent = tPlain("web_waiting_phone");
    share.disabled = true;
    // Telegram sends the contact to the bot; the bot saves it. Poll until it lands.
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      ME = await api("api/me");
      if (ME.phone) {
        haptic("success");
        if (ME.registered) toast(tPlain("reg_done"));
        return route();
      }
    }
    share.disabled = false;
    status.textContent = tPlain("web_error");
  }

  share.addEventListener("click", () => {
    if (!supported) return;
    tg.requestContact((ok) => {
      if (ok) go(waitForPhone);
      else { status.textContent = tPlain("web_phone_declined"); haptic("error"); }
    });
  });

  render(
    h("h1", { text: tPlain("web_phone_label") }),
    h("div", { class: "card" },
      supported
        ? [h("p", { text: tPlain("reg_ask_phone").replace(/\s*👇\s*$/, "") }), share]
        : [h("p", { text: tPlain("web_phone_in_chat") }),
          tg?.close ? h("button", { onclick: () => tg.close(), text: "OK" }) : null],
      status),
    backLink(),
  );
}

function viewLoggedOut() {
  setBack(null);
  render(h("div", { class: "center" },
    h("p", { html: t("logged_out") }),
    h("button", {
      text: tPlain("btn_login"),
      onclick: () => go(async () => {
        ME = await api("api/login", { method: "POST" });
        haptic("success");
        await route();
      }),
    }),
  ));
}

async function viewProfile() {
  setBack(() => go(viewHome));
  render(
    h("div", { class: "card pre", html: t("profile", { name: ME.full_name, phone: ME.phone, group: ME.group_name }) }),
    h("h2", { text: tPlain("choose_language") }),
    h("div", { class: "chips" }, Object.entries(LANGS).map(([code, name]) =>
      h("button", {
        class: code === ME.language ? "active" : "", text: name, "aria-pressed": String(code === ME.language),
        onclick: () => go(async () => {
          ME = await api("api/language", { method: "POST", body: { language: code } });
          await loadTexts(code);
          await viewProfile();
        }),
      }))),
    h("div", { class: "list" },
      h("button", {
        class: "secondary", text: tPlain("btn_edit_profile"),
        onclick: () => go(async () => { ME = await api("api/profile/edit", { method: "POST" }); await route(); }),
      }),
      h("button", {
        class: "danger", text: tPlain("btn_logout"),
        onclick: async () => {
          if (!(await confirmDialog(tPlain("web_logout_confirm")))) return;
          go(async () => { ME = await api("api/logout", { method: "POST" }); await route(); });
        },
      }),
    ),
    backLink(),
  );
}

// ------------------------------------------------------------------ main screens

async function viewHome() {
  setBack(null);
  render(spinner());
  const [me, themes] = await Promise.all([api("api/me"), api("api/themes")]);
  ME = me;
  const active = ME.active_session;
  render(
    h("p", { class: "pre", html: t("welcome", { name: ME.full_name, exam: ME.exam_count }) }),
    active && h("div", { class: "card" },
      h("div", { class: "hint", text: `${modeLabel(active.mode)} · ${active.theme_name}` }),
      h("button", {
        style: "margin-top:8px", text: tPlain("continue", { i: active.current_index + 1, n: active.total }),
        onclick: () => go(resumeQuiz),
      })),
    h("h2", { text: tPlain(themes.length ? "choose_theme" : "no_themes") }),
    h("div", { class: "list" }, themes.map((theme) =>
      h("button", { class: "tile", onclick: () => viewTheme(theme) },
        h("span", { text: "📚 " + theme.name }),
        h("span", { class: "meta", text: String(theme.question_count) })))),
    h("h2", {}),
    h("div", { class: "row" },
      h("button", { class: "secondary", text: tPlain("btn_top"), onclick: () => go(() => viewTop(themes)) }),
      h("button", { class: "secondary", text: tPlain("btn_results"), onclick: () => go(viewResults) })),
    h("div", { class: "list", style: "margin-top:8px" },
      h("button", { class: "secondary", text: tPlain("btn_profile"), onclick: () => go(viewProfile) })),
  );
}

function viewTheme(theme) {
  setBack(() => go(viewHome));
  render(
    h("div", { class: "card pre", html: t("choose_mode", { theme: theme.name, n: theme.question_count }) }),
    h("div", { class: "list" },
      h("button", { text: tPlain("mode_practice"), onclick: () => viewCount(theme) }),
      h("button", {
        class: "secondary", text: tPlain("mode_exam", { n: theme.exam_count }),
        onclick: () => go(() => startQuiz(theme.id, "exam")),
      })),
    backLink(),
  );
}

function viewCount(theme) {
  setBack(() => viewTheme(theme));
  const max = theme.question_count;
  const input = h("input", { id: "count", type: "number", inputmode: "numeric", min: 1, max, value: Math.min(10, max) });
  const error = h("div", { class: "error", role: "alert" });
  const presets = [...PRACTICE_PRESETS.filter((n) => n < max), max];
  const chips = presets.map((n) => h("button", {
    type: "button",
    text: n === max ? tPlain("all_questions", { n }) : String(n),
    onclick: () => { input.value = n; sync(); },
  }));
  function sync() {
    chips.forEach((c, i) => c.classList.toggle("active", Number(input.value) === presets[i]));
  }
  input.addEventListener("input", sync);
  sync();

  render(
    h("h1", { text: theme.name }),
    h("form", {
      onsubmit: (ev) => {
        ev.preventDefault();
        const n = Number(input.value);
        if (!Number.isInteger(n) || n < 1 || n > max) { error.innerHTML = t("invalid_count", { max }); return; }
        go(() => startQuiz(theme.id, "practice", n));
      },
    },
      h("label", { for: "count", text: tPlain("web_choose_count", { max }) }),
      h("div", { class: "chips" }, chips),
      input, error,
      h("button", { type: "submit", text: tPlain("web_start") })),
    backLink(),
  );
}

// ------------------------------------------------------------------ quiz

async function startQuiz(themeId, mode, count) {
  render(spinner());
  const state = await api("api/quiz", { method: "POST", body: { theme_id: themeId, mode, count } });
  viewQuestion(state);
}

async function resumeQuiz() {
  render(spinner());
  const state = await api("api/quiz/active");
  if (!state) return viewHome();
  viewQuestion(state);
}

function viewQuestion(state) {
  if (!state.question) return go(() => viewSummary(state.id));
  setBack(() => go(viewHome)); // the session stays active; "Continue" appears on the home screen
  const q = state.question;
  const isPractice = state.mode === "practice";
  const feedback = h("div", { class: "feedback", role: "status" });
  const next = h("div");
  let answered = false;

  const optionButtons = q.options.map((text, i) =>
    h("button", { class: "option", onclick: () => choose(i) },
      h("span", { class: "letter", text: String.fromCharCode(65 + i) }),
      h("span", { text })));

  async function choose(index) {
    if (answered) return;
    answered = true;
    optionButtons.forEach((b) => (b.disabled = true));
    optionButtons[index].classList.add("chosen");
    haptic("light");
    let res;
    try {
      res = await api(`api/quiz/${state.id}/answer`, {
        method: "POST", body: { position: q.position, option_index: index },
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast(tPlain("stale_button"));
        return go(resumeQuiz);
      }
      answered = false;
      optionButtons.forEach((b) => (b.disabled = false));
      optionButtons[index].classList.remove("chosen");
      toast(tPlain("web_error"));
      return;
    }
    const after = res.state;
    const finished = !after.question;
    const proceed = () => (finished ? go(() => viewSummary(state.id)) : viewQuestion(after));

    if (isPractice) {
      const fb = res.feedback;
      optionButtons[fb.correct_index].classList.add("correct");
      if (!fb.is_correct) optionButtons[index].classList.add("wrong");
      feedback.className = "feedback " + (fb.is_correct ? "ok" : "bad");
      feedback.innerHTML = fb.is_correct
        ? t("correct")
        : t("wrong", { letter: String.fromCharCode(65 + fb.correct_index) });
      haptic(fb.is_correct ? "success" : "error");
      const btn = h("button", { text: tPlain(finished ? "web_results_btn" : "web_next"), onclick: proceed });
      next.replaceChildren(btn);
      btn.focus();
    } else {
      setTimeout(proceed, 250);
    }
  }

  async function stop() {
    if (!(await confirmDialog(tPlain("web_stop_confirm")))) return;
    go(async () => {
      const summary = await api("api/quiz/stop", { method: "POST" });
      if (summary) renderSummary(summary); else await viewHome();
    });
  }

  const done = state.current_index;
  render(
    h("div", { class: "qhead" },
      h("span", { text: `${modeLabel(state.mode)} · ${state.theme.name}` }),
      h("span", { text: `${q.position + 1}/${state.total}` })),
    h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": state.total, "aria-valuenow": done },
      h("div", { style: `width:${(done / state.total) * 100}%` })),
    h("div", { class: "question", text: q.text }),
    h("div", { class: "list" }, optionButtons),
    feedback,
    next,
    h("button", { class: "danger", style: "margin-top:16px", text: tPlain("stop"), onclick: stop }),
  );
}

async function viewSummary(sessionId) {
  render(spinner());
  renderSummary(await api(`api/quiz/${sessionId}/summary`));
}

function renderSummary(s) {
  setBack(() => go(viewHome));
  const stopped = s.status !== "finished";
  const again = () => go(() => startQuiz(s.theme.id, s.mode, s.mode === "practice" ? s.total : undefined));
  render(
    h("p", { html: t("result_title", { mode: modeLabel(s.mode), theme: s.theme.name }) }),
    h("div", { class: "card score" },
      stopped && h("p", { class: "hint", html: t("stopped") }),
      h("div", { class: "big", text: `${s.percent}%` }),
      h("p", { html: t("result_score", { c: s.correct, n: s.base, p: s.percent }) }),
      stopped && h("p", { class: "hint", html: t("result_answered", { a: s.answered, n: s.total }) })),
    s.mode === "exam" && s.answered > 0 && [
      h("h2", { html: t("review_title") }),
      s.mistakes.length === 0
        ? h("div", { class: "card", html: t("review_perfect") })
        : s.mistakes.map((m) => h("div", { class: "card mistake" },
          h("div", { class: "q", text: `${m.position + 1}. ${m.question}` }),
          h("div", { class: "yours", text: `❌ ${tPlain("review_yours")}: ${m.chosen_letter}) ${m.chosen_text}` }),
          h("div", { class: "right", text: `✅ ${tPlain("review_correct")}: ${m.correct_letter}) ${m.correct_text}` }))),
    ],
    h("div", { class: "row", style: "margin-top:12px" },
      h("button", { text: tPlain("again"), onclick: again }),
      h("button", { class: "secondary", text: tPlain("menu"), onclick: () => go(viewHome) })),
  );
  haptic(stopped ? "warning" : "success");
}

// ------------------------------------------------------------------ results & leaderboard

async function viewResults() {
  setBack(() => go(viewHome));
  render(spinner());
  const items = await api("api/results");
  render(
    h("h1", { html: t("results_title") }),
    items.length === 0
      ? h("p", { class: "hint", text: tPlain("results_empty") })
      : h("div", { class: "list" }, items.map((r) => h("div", { class: "card" },
        h("div", { class: "hint", text: `${new Date(r.finished_at).toLocaleDateString(textsLang)} · ${modeLabel(r.mode)}` }),
        h("div", { text: r.theme_name }),
        h("strong", { text: `${r.correct}/${r.total} (${Math.round((r.correct * 100) / r.total)}%)` })))),
    backLink(),
  );
}

async function viewTop(themes, themeId) {
  setBack(() => go(viewHome));
  themes = themes || (await api("api/themes"));
  if (!themes.length) return render(h("p", { text: tPlain("no_themes") }), backLink());
  themeId = themeId ?? themes[0].id;

  const tabs = h("div", { class: "chips tabs" }, themes.map((th) => h("button", {
    class: th.id === themeId ? "active" : "", text: th.name, "aria-pressed": String(th.id === themeId),
    onclick: () => go(() => viewTop(themes, th.id)),
  })));
  render(h("h1", { text: tPlain("btn_top") }), tabs, spinner());

  const data = await api(`api/leaderboard/${themeId}`);
  const rows = data.top.map((e) => h("tr", { class: e.is_me ? "me" : "" },
    h("td", { class: "rank", text: MEDALS[e.rank] || String(e.rank) }),
    h("td", {},
      h("div", { text: e.name + (e.is_me ? ` (${tPlain("web_you")})` : "") }),
      e.group && h("div", { class: "sub", text: e.group })),
    h("td", { class: "num" },
      h("div", {}, h("strong", { text: `${e.correct}/${e.total}` })),
      h("div", { class: "sub", text: `${e.percent}% · ⏱ ${e.duration}` }))));

  render(
    h("h1", { text: tPlain("btn_top") }),
    tabs,
    h("p", { class: "pre", html: t("top_title", { theme: data.theme.name }) }),
    h("div", { class: "card" },
      rows.length ? h("table", { class: "board" }, h("tbody", {}, rows)) : h("p", { class: "hint", text: tPlain("top_empty") })),
    h("p", {
      html: data.me
        ? t("top_you", { rank: data.me.rank, c: data.me.correct, n: data.me.total, p: data.me.percent })
        : t("top_you_none"),
    }),
    h("button", {
      class: "secondary", text: tPlain("mode_exam", { n: themes.find((x) => x.id === themeId).exam_count }),
      onclick: () => go(() => startQuiz(themeId, "exam")),
    }),
    backLink(),
  );
}

go(boot);
