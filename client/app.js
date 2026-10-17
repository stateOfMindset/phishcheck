// PhishCheck client: plain JavaScript, talks to the Flask server over JSON/REST only.
(() => {
  "use strict";

  const SESSION_KEY = "phishcheck.session";
  const chat = document.getElementById("chat");
  const welcome = document.getElementById("welcome");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendButton = document.getElementById("send");
  const health = document.getElementById("health");

  const ROUTE_LABELS = { tool: "Tool", rag: "RAG", direct: "Direct LLM" };
  const ASSESSMENT_LABELS = {
    high_risk_indicators: "High-risk warning signs",
    warning_signs: "Some warning signs",
    no_structural_red_flags: "No structural red flags (not proof of safety)",
  };

  // ------------------------------------------------------------------ session
  function newSessionId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function storage(action, value) {
    try {
      if (action === "get") return localStorage.getItem(SESSION_KEY);
      localStorage.setItem(SESSION_KEY, value);
    } catch (_) { /* private mode: session lasts until reload */ }
    return null;
  }

  let sessionId = storage("get") || newSessionId();
  storage("set", sessionId);
  let busy = false;  // true while a request is in flight or history is loading

  // ------------------------------------------------------------------ rendering helpers
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  // Inline Markdown on already-escaped text. URLs are deliberately NOT turned into links:
  // this app discusses phishing links, and nothing in an answer should be one click away.
  function inline(text) {
    return text
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/\[(\d{1,2})\]/g, '<span class="cite">[$1]</span>');
  }

  // Small, safe Markdown subset: paragraphs, headings, bullet/numbered lists, rules and fenced
  // code blocks. The whole text is HTML-escaped first, so nothing in an answer can become markup.
  function renderMarkdown(source) {
    const lines = escapeHtml(source).split(/\r?\n/);
    let html = "";
    let list = null;      // "ul" | "ol" | null
    let paragraph = [];
    let code = null;      // lines of the open ``` block, or null

    const flushParagraph = () => {
      if (paragraph.length) html += `<p>${inline(paragraph.join("<br>"))}</p>`;
      paragraph = [];
    };
    const closeList = () => {
      if (list) html += `</${list}>`;
      list = null;
    };

    for (const raw of lines) {
      const line = raw.trimEnd();
      let m;
      // Fenced code: keep the lines exactly as written (indentation, '#' comments), no Markdown.
      if (/^\s*```/.test(line)) {
        if (code === null) { flushParagraph(); closeList(); code = []; }
        else { html += `<pre dir="ltr"><code>${code.join("\n")}</code></pre>`; code = null; }
        continue;
      }
      if (code !== null) { code.push(raw); continue; }
      if (!line.trim()) { flushParagraph(); closeList(); continue; }
      if (/^\s*(---|\*\*\*)\s*$/.test(line)) { flushParagraph(); closeList(); html += "<hr>"; continue; }
      if ((m = line.match(/^\s*#{1,4}\s+(.*)$/))) {
        flushParagraph(); closeList(); html += `<h4>${inline(m[1])}</h4>`; continue;
      }
      if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
        flushParagraph();
        if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; }
        html += `<li>${inline(m[1])}</li>`; continue;
      }
      if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        flushParagraph();
        if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; }
        html += `<li>${inline(m[1])}</li>`; continue;
      }
      closeList();
      paragraph.push(line);
    }
    if (code !== null) html += `<pre dir="ltr"><code>${code.join("\n")}</code></pre>`;  // unclosed fence
    flushParagraph();
    closeList();
    return html;
  }

  function scrollToBottom() {
    chat.scrollTop = chat.scrollHeight;
  }

  function hideWelcome() {
    welcome.hidden = true;
  }

  // ------------------------------------------------------------------ messages
  function addUserMessage(text) {
    hideWelcome();
    const wrap = el("div", "msg user");
    const bubble = el("div", "bubble", text);
    bubble.dir = "auto";
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function routeMeta(data) {
    const meta = el("div", "meta");
    (data.routes || []).forEach((route) => {
      meta.appendChild(el("span", `route ${route}`, ROUTE_LABELS[route] || route));
    });
    if (data.router === "rules") {
      meta.appendChild(el("span", "router-kind", "(rule-based fallback router)"));
    }
    if (data.route_reason) meta.appendChild(el("span", "reason", data.route_reason));
    return meta;
  }

  function sourcesDetails(sources) {
    const details = el("details");
    details.appendChild(el("summary", null, `Sources (${sources.length})`));
    sources.forEach((s) => {
      const row = el("div", "source");
      const label = s.source_type === "college" ? "College procedure (sample)" : "General guidance";
      row.appendChild(el("span", "tag", `[${s.n}]`));
      row.appendChild(el("span", "tag", label));
      row.appendChild(el("strong", null, s.title));
      row.appendChild(document.createTextNode(` > ${s.heading} `));
      row.appendChild(el("span", "score", `similarity ${Number(s.score).toFixed(3)}`));
      if (s.source_url) {
        row.appendChild(document.createTextNode(" · "));
        const link = el("a", null, "original source");
        link.href = s.source_url;          // only our own curated, official sources
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        row.appendChild(link);
      }
      details.appendChild(row);
    });
    return details;
  }

  function toolDetails(toolCalls) {
    const details = el("details");
    details.open = true;
    details.appendChild(el("summary", null, `What the checks found (${toolCalls.length})`));
    toolCalls.forEach((call) => {
      const row = el("div", "finding");
      const name = call.tool === "inspect_url" ? "Link check" : "Email header check";
      row.appendChild(el("strong", null, `${name}: `));
      const target = el("span", "target", (call.input || "").split("\n")[0].slice(0, 120));
      row.appendChild(target);
      row.appendChild(el("br"));
      if (call.error) {
        row.appendChild(el("span", "assessment high_risk_indicators", `Could not run: ${call.error}`));
      } else {
        row.appendChild(el("span", `assessment ${call.assessment}`,
          ASSESSMENT_LABELS[call.assessment] || call.assessment));
        (call.indicators || []).forEach((ind) => {
          const item = el("span", `indicator ${ind.severity}`);
          item.appendChild(el("span", "sev", ind.severity));
          item.appendChild(document.createTextNode(ind.detail));
          row.appendChild(item);
        });
      }
      details.appendChild(row);
    });
    return details;
  }

  const reducedMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const BLOCKS = "p, li, h4, pre";
  const MAX_FRAMES = 150;   // the whole answer is typed out in at most ~2.5 s at 60 fps

  function nearBottom() {
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 120;
  }

  // Types the already-rendered HTML in `bubble` out character by character. Each paragraph or
  // list item stays hidden until the text reaches it, then slides and fades in.
  function typeOut(bubble) {
    return new Promise((resolve) => {
      if (reducedMotion) { resolve(); return; }
      const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
      const parts = [];
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        parts.push({ node, text: node.nodeValue });
        node.nodeValue = "";
      }
      bubble.querySelectorAll(BLOCKS).forEach((b) => b.classList.add("pending"));
      const total = parts.reduce((sum, p) => sum + p.text.length, 0);
      const perFrame = Math.max(2, Math.ceil(total / MAX_FRAMES));
      const caret = el("span", "caret");
      let index = 0;
      let offset = 0;

      function frame() {
        const follow = nearBottom();
        let budget = perFrame;
        while (budget > 0 && index < parts.length) {
          const part = parts[index];
          const block = part.node.parentElement && part.node.parentElement.closest(BLOCKS);
          if (block && block.classList.contains("pending")) {
            block.classList.remove("pending");
            block.classList.add("reveal");
          }
          const take = Math.min(budget, part.text.length - offset);
          offset += take;
          budget -= take;
          part.node.nodeValue = part.text.slice(0, offset);
          part.node.after(caret);
          if (offset >= part.text.length) { index += 1; offset = 0; }
        }
        if (follow) scrollToBottom();
        if (index < parts.length) {
          requestAnimationFrame(frame);
        } else {
          caret.remove();
          bubble.querySelectorAll(".pending").forEach((b) => b.classList.remove("pending"));
          resolve();
        }
      }
      requestAnimationFrame(frame);
    });
  }

  async function addAssistantMessage(data, animate = false) {
    hideWelcome();
    const wrap = el("div", "msg assistant");
    if (data.routes && data.routes.length) {
      const meta = routeMeta(data);
      if (animate) meta.classList.add("reveal");
      wrap.appendChild(meta);
    }
    const bubble = el("div", "bubble");
    bubble.dir = "auto";
    // Safety net: an empty answer should never reach here, but a blank bubble looks broken.
    bubble.innerHTML = renderMarkdown(data.answer || "*(No answer was returned. Please try again.)*");
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    scrollToBottom();
    if (animate) await typeOut(bubble);

    const extras = [];
    if (data.tool_calls && data.tool_calls.length) extras.push(toolDetails(data.tool_calls));
    if (data.sources && data.sources.length) extras.push(sourcesDetails(data.sources));
    extras.forEach((node) => {
      if (animate) node.classList.add("reveal");
      wrap.appendChild(node);
    });
    if (animate && nearBottom()) scrollToBottom();
  }

  function addError(text) {
    const wrap = el("div", "msg assistant error");
    wrap.appendChild(el("div", "bubble", text));
    chat.appendChild(wrap);
    scrollToBottom();
  }

  // ------------------------------------------------------------------ rate-limit cooldown
  // After a 429 the server says how long to wait (Retry-After). Count it down live and keep
  // Send disabled until then, instead of showing a number that is out of date a second later.
  let cooldownUntil = 0;
  let cooldownNotice = null;

  function coolingDown() {
    return Date.now() < cooldownUntil;
  }

  function startCooldown(seconds) {
    cooldownUntil = Date.now() + seconds * 1000;
    if (cooldownNotice) cooldownNotice.remove();
    const wrap = el("div", "msg assistant error");
    const bubble = el("div", "bubble");
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    cooldownNotice = wrap;
    sendButton.disabled = true;

    const tick = () => {
      const left = Math.ceil((cooldownUntil - Date.now()) / 1000);
      if (left > 0) {
        bubble.textContent = `Too many messages. You can send again in ${left}s. ` +
          "Your message is back in the box below.";
        return;
      }
      clearInterval(timer);
      wrap.classList.remove("error");
      bubble.textContent = "You can send messages again.";
      if (!busy) sendButton.disabled = false;
    };
    const timer = setInterval(tick, 250);
    tick();
    scrollToBottom();
  }

  function addTyping() {
    const wrap = el("div", "msg assistant");
    const bubble = el("div", "bubble");
    const dots = el("span", "typing");
    dots.append(el("span"), el("span"), el("span"));
    const label = el("span", "typing-label", "Routing your question…");
    bubble.append(dots, label);
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    scrollToBottom();
    // The labels are indicative only; the real route is shown when the answer arrives.
    const steps = ["Checking and searching the guides…", "Writing the answer…"];
    let i = 0;
    const timer = setInterval(() => { if (i < steps.length) label.textContent = steps[i++]; }, 2500);
    return () => { clearInterval(timer); wrap.remove(); };
  }

  // ------------------------------------------------------------------ server calls
  async function fetchJson(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (_) {
      throw new Error("Cannot reach the PhishCheck server. Is it running?");
    }
    let body = null;
    try { body = await response.json(); } catch (_) { /* non-JSON error page */ }
    if (!response.ok) {
      const err = new Error((body && body.error) || `The server returned an error (${response.status}).`);
      err.status = response.status;
      err.retryAfter = parseInt(response.headers.get("Retry-After"), 10) || null;
      throw err;
    }
    return body;
  }

  async function checkHealth() {
    try {
      const data = await fetchJson("/health");
      health.className = "health ok";
      health.textContent = `online · ${data.knowledge_chunks} knowledge chunks`;
      if (!data.llm_configured) {
        health.className = "health bad";
        health.textContent = "API key missing";
      }
    } catch (_) {
      health.className = "health bad";
      health.textContent = "offline";
    }
  }

  async function loadHistory() {
    // Block sending until the earlier messages are on screen, so a new message can never be
    // drawn above the history.
    busy = true;
    sendButton.disabled = true;
    try {
      const data = await fetchJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
      data.messages.forEach((m) => {
        if (m.role === "user") addUserMessage(m.content);
        else addAssistantMessage({
          answer: m.content, routes: m.routes, route_reason: m.route_reason, sources: m.sources || [],
        });
      });
    } catch (err) {
      addError(err.message);
    } finally {
      busy = false;
      sendButton.disabled = coolingDown();
    }
  }

  async function send(text) {
    const message = text.trim();
    if (!message || busy || coolingDown()) return;
    busy = true;
    sendButton.disabled = true;
    const userBubble = addUserMessage(message);
    input.value = "";
    autoResize();
    const stopTyping = addTyping();
    try {
      const data = await fetchJson("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message }),
      });
      stopTyping();
      await addAssistantMessage(data, true);
    } catch (err) {
      stopTyping();
      if (err.status === 429) {
        // The server rejected the message without saving it: take its bubble away and put the
        // text back in the box so it can be sent once the countdown ends.
        userBubble.remove();
        if (!input.value) { input.value = message; autoResize(); }
        startCooldown(err.retryAfter || 60);
      } else {
        addError(err.message);
      }
    } finally {
      busy = false;
      sendButton.disabled = coolingDown();
      input.focus();
    }
  }

  // ------------------------------------------------------------------ events
  function autoResize() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight + 2, 200)}px`;
    input.style.overflowY = input.scrollHeight > 200 ? "auto" : "hidden";
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  input.addEventListener("input", autoResize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
  });
  document.querySelectorAll(".example").forEach((button) => {
    button.addEventListener("click", () => send(button.textContent));
  });
  document.getElementById("new-chat").addEventListener("click", () => {
    sessionId = newSessionId();
    storage("set", sessionId);
    chat.querySelectorAll(".msg").forEach((node) => node.remove());
    welcome.hidden = false;
    input.focus();
  });

  checkHealth();
  loadHistory();
  autoResize();
  input.focus();
})();
