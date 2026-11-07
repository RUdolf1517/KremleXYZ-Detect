var KremleWidget = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // src/index.js
  var index_exports = {};
  __export(index_exports, {
    autoMount: () => autoMount,
    collectFingerprint: () => collectFingerprint,
    createWidget: () => createWidget,
    mount: () => mount,
    resultMessage: () => resultMessage
  });

  // src/fingerprint.js
  function collectFingerprint(honeypot = {}) {
    const fp = {
      yaBrands: false,
      yandexApi: false,
      honeypot: false,
      webdriver: false,
      timezone: ""
    };
    try {
      const uaData = navigator.userAgentData;
      if (uaData && Array.isArray(uaData.brands)) {
        fp.yaBrands = uaData.brands.some(
          (entry) => /YaBrowser|Yandex/i.test(entry && entry.brand || "")
        );
      }
      if (!fp.yaBrands) {
        fp.yaBrands = /YaBrowser|Yowser/i.test(navigator.userAgent || "");
      }
      fp.yandexApi = Boolean(window.yandex || window.Ya || window.YaBrowser);
      fp.webdriver = Boolean(navigator.webdriver);
      fp.honeypot = Boolean(
        honeypot.name && honeypot.name.trim().length > 0 || honeypot.email && honeypot.email.trim().length > 0
      );
      try {
        fp.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      } catch (e) {
        fp.timezone = "";
      }
    } catch (e) {
      fp.error = e && e.message;
    }
    return fp;
  }

  // src/widget.js
  var STYLE = {
    root: {
      fontFamily: "monospace",
      background: "#0a0a0a",
      color: "#ffffff",
      padding: "2rem",
      maxWidth: "600px",
      border: "1px solid #2a2a2a",
      boxSizing: "border-box"
    },
    title: { fontSize: "1.25rem", margin: "0 0 0.5rem", letterSpacing: "0.05em" },
    description: {
      color: "#888888",
      fontSize: "0.85rem",
      margin: "0 0 1.25rem",
      lineHeight: "1.5"
    },
    timer: { color: "#666666", fontSize: "0.75rem", margin: "0 0 1rem" },
    timerWarn: { color: "#ff9c9c", fontSize: "0.75rem", margin: "0 0 1rem" },
    question: {
      margin: "0 0 1.25rem",
      padding: "0 0 1.25rem",
      borderBottom: "1px solid #1e1e1e"
    },
    questionText: { margin: "0 0 0.6rem", lineHeight: "1.5", color: "#cccccc" },
    image: {
      maxWidth: "100%",
      maxHeight: "220px",
      display: "block",
      margin: "0.35rem 0",
      border: "1px solid #2a2a2a",
      background: "#ffffff"
    },
    label: {
      display: "flex",
      alignItems: "center",
      gap: "0.5rem",
      padding: "0.3rem 0",
      cursor: "pointer",
      color: "#666666"
    },
    labelSelected: { color: "#ffffff" },
    radio: { accentColor: "#ffffff", cursor: "pointer" },
    button: {
      marginTop: "1rem",
      background: "transparent",
      border: "1px solid #ffffff",
      color: "#ffffff",
      fontFamily: "monospace",
      fontSize: "1rem",
      padding: "0.5rem 1.25rem",
      cursor: "pointer",
      letterSpacing: "0.04em"
    },
    buttonDisabled: { opacity: "0.35", cursor: "not-allowed" },
    hint: { color: "#888888", fontSize: "0.85rem", marginTop: "0.75rem" },
    result: { marginTop: "1rem", padding: "0.75rem 1rem", border: "1px solid" },
    resultPass: { borderColor: "#4caf50", color: "#4caf50" },
    resultFail: { borderColor: "#f44336", color: "#f44336" },
    error: { color: "#f44336", margin: "0 0 0.75rem" },
    honeypot: {
      position: "absolute",
      left: "-9999px",
      top: "-9999px",
      width: "1px",
      height: "1px",
      opacity: "0",
      pointerEvents: "none"
    },
    attribution: {
      marginTop: "1.25rem",
      paddingTop: "0.75rem",
      borderTop: "1px solid #1e1e1e",
      color: "#666666",
      fontSize: "0.75rem"
    },
    attributionLink: { color: "#888888" }
  };
  var DEFAULTS = {
    challengeUrl: "/kremle/challenge",
    verifyUrl: "/kremle/verify",
    logoutUrl: null,
    title: "[ \u043F\u0440\u043E\u0432\u0435\u0440\u043A\u0430 ]",
    description: null,
    submitText: "\u043F\u0440\u043E\u0432\u0435\u0440\u0438\u0442\u044C",
    retryText: "\u043D\u0430\u0447\u0430\u0442\u044C \u0437\u0430\u043D\u043E\u0432\u043E",
    showAttribution: true,
    showTimer: true,
    autoReloadOnExpired: true,
    redirectOnPass: false,
    fingerprint: null,
    fetch: null,
    onPass: null,
    onFail: null,
    onError: null
  };
  var TEXT = {
    loading: "\u0437\u0430\u0433\u0440\u0443\u0437\u043A\u0430\u2026",
    noQuestions: "\u0432\u043E\u043F\u0440\u043E\u0441\u044B \u043D\u0435 \u043F\u0440\u0438\u0448\u043B\u0438 \u2014 \u043F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437",
    unanswered: "\u043E\u0442\u0432\u0435\u0442\u044C\u0442\u0435 \u043D\u0430 \u0432\u0441\u0435 \u0432\u043E\u043F\u0440\u043E\u0441\u044B",
    network: "\u0441\u0435\u0442\u044C \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u043D\u0430 \u2014 \u043F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u043F\u043E\u0437\u0436\u0435",
    expired: "\u043F\u0440\u043E\u0432\u0435\u0440\u043A\u0430 \u0443\u0441\u0442\u0430\u0440\u0435\u043B\u0430 \u2014 \u043E\u0431\u043D\u043E\u0432\u0438\u0442\u0435 \u0435\u0451",
    rateLimited: "\u0441\u043B\u0438\u0448\u043A\u043E\u043C \u043C\u043D\u043E\u0433\u043E \u043F\u043E\u043F\u044B\u0442\u043E\u043A \u2014 \u043F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u043F\u043E\u0437\u0436\u0435",
    blocked: "\u0434\u043E\u0441\u0442\u0443\u043F \u0437\u0430\u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u0430\u043D",
    invalidToken: "\u043F\u0440\u043E\u0432\u0435\u0440\u043A\u0430 \u0443\u0441\u0442\u0430\u0440\u0435\u043B\u0430 \u2014 \u043D\u0430\u0447\u043D\u0438\u0442\u0435 \u0437\u0430\u043D\u043E\u0432\u043E"
  };
  function node(tag, style, text) {
    const element = document.createElement(tag);
    if (style) Object.assign(element.style, style);
    if (text !== void 0 && text !== null) element.textContent = String(text);
    return element;
  }
  function formatLeft(seconds) {
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return `${minutes}:${rest < 10 ? "0" : ""}${rest}`;
  }
  function deriveLogoutUrl(verifyUrl) {
    return String(verifyUrl).replace(/\/verify\/?$/, "/logout");
  }
  function resultMessage(result) {
    if (!result) return "";
    if (result.passed) return `\u043F\u0440\u043E\u0439\u0434\u0435\u043D\u043E \u2014 \u043E\u0448\u0438\u0431\u043E\u043A: ${result.errors}/${result.total}`;
    if (result.error === "rate_limited") return TEXT.rateLimited;
    if (result.error === "blacklisted" || result.error === "blocked") return TEXT.blocked;
    if (result.error === "invalid_token") return TEXT.invalidToken;
    if (result.error) return `\u043E\u0448\u0438\u0431\u043A\u0430: ${result.error}`;
    if (typeof result.max_errors === "number") {
      return `\u043F\u0440\u043E\u0432\u0430\u043B \u2014 \u043E\u0448\u0438\u0431\u043E\u043A: ${result.errors} \u0438\u0437 ${result.max_errors} \u0434\u043E\u043F\u0443\u0441\u0442\u0438\u043C\u044B\u0445`;
    }
    return `\u043F\u0440\u043E\u0432\u0430\u043B \u2014 \u043E\u0448\u0438\u0431\u043E\u043A: ${result.errors}/${result.total}`;
  }
  function createWidget(target, options = {}) {
    const config = { ...DEFAULTS, ...options };
    const host = typeof target === "string" ? document.querySelector(target) : target;
    if (!host) {
      throw new Error(`kremle-widget: \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u044D\u043B\u0435\u043C\u0435\u043D\u0442 ${String(target)}`);
    }
    const fetchImpl = config.fetch || ((...args) => window.fetch(...args));
    const state = {
      questions: [],
      token: "",
      answers: {},
      sources: [],
      attribution: "",
      maxErrors: void 0,
      expiresAt: null,
      loading: false,
      submitting: false,
      result: null,
      error: null,
      destroyed: false
    };
    const root = node("div", STYLE.root);
    root.className = "kremle-widget";
    root.setAttribute("role", "region");
    root.setAttribute("aria-label", config.title);
    const header = node("h2", STYLE.title, config.title);
    root.appendChild(header);
    const body = node("div");
    root.appendChild(body);
    const honeypotWrap = node("div", STYLE.honeypot);
    honeypotWrap.setAttribute("aria-hidden", "true");
    const honeypotName = node("input");
    honeypotName.type = "text";
    honeypotName.name = "kremle_name";
    honeypotName.tabIndex = -1;
    honeypotName.autocomplete = "off";
    const honeypotEmail = node("input");
    honeypotEmail.type = "email";
    honeypotEmail.name = "kremle_email";
    honeypotEmail.tabIndex = -1;
    honeypotEmail.autocomplete = "off";
    honeypotWrap.appendChild(honeypotName);
    honeypotWrap.appendChild(honeypotEmail);
    root.appendChild(honeypotWrap);
    host.innerHTML = "";
    host.appendChild(root);
    let timerId = null;
    function stopTimer() {
      if (timerId !== null) {
        clearInterval(timerId);
        timerId = null;
      }
    }
    function secondsLeft() {
      if (state.expiresAt === null) return null;
      return Math.max(0, Math.round((state.expiresAt - Date.now()) / 1e3));
    }
    function render() {
      if (state.destroyed) return;
      body.innerHTML = "";
      if (config.description) {
        body.appendChild(node("p", STYLE.description, config.description));
      }
      if (state.loading) {
        body.appendChild(node("p", STYLE.hint, TEXT.loading));
        return;
      }
      if (state.error) {
        body.appendChild(node("p", STYLE.error, state.error));
      }
      if (!state.questions.length) {
        if (!state.loading) {
          const retryButton = node("button", STYLE.button, config.retryText);
          retryButton.type = "button";
          retryButton.addEventListener("click", () => void load());
          body.appendChild(retryButton);
        }
        return;
      }
      const left = secondsLeft();
      if (config.showTimer && left !== null) {
        const style = left <= 60 ? STYLE.timerWarn : STYLE.timer;
        body.appendChild(node("p", style, `\u043E\u0441\u0442\u0430\u043B\u043E\u0441\u044C ${formatLeft(left)}`));
      }
      state.questions.forEach((question, index) => {
        body.appendChild(renderQuestion(question, index));
      });
      const submitButton = node("button", STYLE.button, config.submitText);
      submitButton.type = "button";
      submitButton.className = "kremle-submit";
      if (state.submitting) {
        Object.assign(submitButton.style, STYLE.buttonDisabled);
        submitButton.disabled = true;
      }
      submitButton.addEventListener("click", () => void submit());
      body.appendChild(submitButton);
      if (!allAnswered()) {
        body.appendChild(node("p", STYLE.hint, TEXT.unanswered));
      }
      if (state.result) {
        const style = { ...STYLE.result, ...state.result.passed ? STYLE.resultPass : STYLE.resultFail };
        const box = node("div", style, resultMessage(state.result));
        box.className = "kremle-result";
        body.appendChild(box);
        const again = node("button", STYLE.button, config.retryText);
        again.type = "button";
        again.className = "kremle-retry";
        again.addEventListener("click", () => void retry());
        body.appendChild(again);
      }
      if (config.showAttribution && state.attribution) {
        const footer = node("div", STYLE.attribution);
        footer.appendChild(node("span", null, state.attribution));
        const link = state.sources.find((source) => source && source.url);
        if (link) {
          const anchor = node("a", STYLE.attributionLink, link.name || link.url);
          anchor.href = link.url;
          anchor.target = "_blank";
          anchor.rel = "noopener nofollow";
          footer.appendChild(node("span", null, " \u2014 "));
          footer.appendChild(anchor);
        }
        body.appendChild(footer);
      }
    }
    function renderQuestion(question, index) {
      const block = node("div", STYLE.question);
      block.appendChild(node("p", STYLE.questionText, `${index + 1}. ${question.q || ""}`));
      if (Array.isArray(question.images)) {
        question.images.forEach((image) => {
          if (!image || !image.url) return;
          const img = node("img", STYLE.image);
          img.src = image.url;
          img.alt = image.alt || "";
          img.loading = "lazy";
          block.appendChild(img);
        });
      }
      const options2 = Array.isArray(question.opts) ? question.opts : [];
      options2.forEach((option, optionIndex) => {
        const label = node("label", STYLE.label);
        const input = node("input", STYLE.radio);
        input.type = "radio";
        input.name = `kremle-q${index}`;
        input.value = String(optionIndex);
        input.checked = state.answers[String(index)] === optionIndex;
        const text = node("span", null, option);
        label.appendChild(input);
        label.appendChild(text);
        if (input.checked) Object.assign(label.style, STYLE.labelSelected);
        input.addEventListener("change", () => {
          state.answers[String(index)] = optionIndex;
          render();
        });
        block.appendChild(label);
      });
      return block;
    }
    function allAnswered() {
      return state.questions.length > 0 && state.questions.every((_, index) => state.answers[String(index)] !== void 0);
    }
    async function load() {
      stopTimer();
      state.loading = true;
      state.error = null;
      state.result = null;
      render();
      try {
        const response = await fetchImpl(config.challengeUrl, {
          credentials: "include",
          headers: { Accept: "application/json" }
        });
        if (!response.ok) {
          throw new Error(response.status === 429 ? TEXT.rateLimited : `HTTP ${response.status}`);
        }
        const data = await response.json();
        if (state.destroyed) return;
        state.questions = Array.isArray(data.questions) ? data.questions : [];
        state.token = data.token || "";
        state.sources = Array.isArray(data.sources) ? data.sources : [];
        state.attribution = data.attribution || "";
        state.maxErrors = typeof data.max_errors === "number" ? data.max_errors : void 0;
        state.expiresAt = typeof data.expires_in === "number" ? Date.now() + data.expires_in * 1e3 : null;
        state.answers = {};
        if (!state.questions.length) state.error = TEXT.noQuestions;
      } catch (e) {
        if (state.destroyed) return;
        state.error = e && e.message ? e.message : TEXT.network;
        state.questions = [];
        if (config.onError) config.onError(state.error);
      } finally {
        if (!state.destroyed) {
          state.loading = false;
          render();
          startTimer();
        }
      }
    }
    function startTimer() {
      stopTimer();
      if (state.expiresAt === null) return;
      timerId = setInterval(() => {
        if (state.destroyed) {
          stopTimer();
          return;
        }
        const left = secondsLeft();
        if (left !== null && left <= 0) {
          stopTimer();
          if (config.autoReloadOnExpired) void load();
          else render();
          return;
        }
        render();
      }, 1e3);
    }
    async function submit() {
      if (state.submitting || !state.questions.length) return;
      if (!allAnswered()) {
        state.error = TEXT.unanswered;
        render();
        return;
      }
      state.submitting = true;
      state.error = null;
      render();
      const fingerprint = (config.fingerprint || collectFingerprint)({
        name: honeypotName.value,
        email: honeypotEmail.value
      });
      try {
        const response = await fetchImpl(config.verifyUrl, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ token: state.token, answers: state.answers, fingerprint })
        });
        const data = await response.json();
        if (state.destroyed) return data;
        state.result = data;
        if (data.error === "invalid_token" && config.autoReloadOnExpired) {
          state.submitting = false;
          await load();
          return data;
        }
        if (data.passed) {
          if (config.onPass) config.onPass(data);
          if (config.redirectOnPass && data.redirect) {
            window.location.assign(data.redirect);
            return data;
          }
        } else if (config.onFail) {
          config.onFail(data);
        }
        return data;
      } catch (e) {
        if (state.destroyed) return null;
        state.error = TEXT.network;
        if (config.onError) config.onError(state.error);
        return null;
      } finally {
        if (!state.destroyed) {
          state.submitting = false;
          render();
        }
      }
    }
    async function retry() {
      const url = config.logoutUrl || deriveLogoutUrl(config.verifyUrl);
      try {
        await fetchImpl(url, { method: "POST", credentials: "include" });
      } catch (e) {
      }
      await load();
    }
    function destroy() {
      stopTimer();
      state.destroyed = true;
      root.remove();
    }
    function getState() {
      return { ...state, answers: { ...state.answers } };
    }
    render();
    void load();
    return {
      element: root,
      load,
      reload: load,
      retry,
      submit,
      destroy,
      getState
    };
  }
  function mount(target, options = {}) {
    return createWidget(target, options);
  }
  function autoMount(rootDocument = typeof document === "undefined" ? null : document, defaults = {}) {
    if (!rootDocument) return [];
    const nodes = Array.from(rootDocument.querySelectorAll("[data-kremle]"));
    return nodes.map((element) => {
      const dataset = element.dataset || {};
      const options = { ...defaults };
      if (dataset.challengeUrl) options.challengeUrl = dataset.challengeUrl;
      if (dataset.verifyUrl) options.verifyUrl = dataset.verifyUrl;
      if (dataset.logoutUrl) options.logoutUrl = dataset.logoutUrl;
      if (dataset.title) options.title = dataset.title;
      if (dataset.redirect === "true") options.redirectOnPass = true;
      return createWidget(element, options);
    });
  }
  return __toCommonJS(index_exports);
})();
//# sourceMappingURL=kremle-widget.js.map
