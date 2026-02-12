/* Amplifier Web — WebSocket client */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Markdown setup
  // ---------------------------------------------------------------------------
  marked.setOptions({
    breaks: true,
    gfm: true,
    highlight: function (code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        try { return hljs.highlight(code, { language: lang }).value; }
        catch (_) { /* fall through */ }
      }
      return hljs.highlightAuto(code).value;
    },
  });

  // ---------------------------------------------------------------------------
  // DOM refs
  // ---------------------------------------------------------------------------
  const messagesEl    = document.getElementById("messages");
  const inputEl       = document.getElementById("chat-input");
  const sendBtn       = document.getElementById("send-btn");
  const statusEl      = document.getElementById("status-text");
  const modelEl       = document.getElementById("model-name");
  const tokenEl       = document.getElementById("token-count");
  const indicatorEl   = document.getElementById("streaming-indicator");
  var sidebarEl = document.getElementById("sidebar");
  var sidebarToggleEl = document.getElementById("sidebar-toggle");
  var newSessionBtn = document.getElementById("new-session-btn");
  var sidebarCloseBtn = document.getElementById("sidebar-close");
  var sessionListEl = document.getElementById("session-list");
  var paletteOverlay = document.getElementById("command-palette");
  var paletteInput = document.getElementById("palette-input");
  var paletteResults = document.getElementById("palette-results");

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let ws = null;
  let currentStreamEl = null;   // element receiving streaming deltas
  let reconnectDelay  = 1000;

  // ---------------------------------------------------------------------------
  // WebSocket lifecycle
  // ---------------------------------------------------------------------------
  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws");

    ws.onopen = function () {
      statusEl.textContent = "Connected";
      statusEl.classList.remove("status-error");
      statusEl.classList.add("status-ok");
      reconnectDelay = 1000;
    };

    ws.onclose = function () {
      statusEl.textContent = "Disconnected";
      statusEl.classList.remove("status-ok");
      statusEl.classList.add("status-error");
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };

    ws.onerror = function () {
      statusEl.textContent = "Connection error";
      statusEl.classList.add("status-error");
    };

    ws.onmessage = function (evt) {
      var data;
      try { data = JSON.parse(evt.data); } catch (_) { return; }
      handleEvent(data);
    };
  }

  // ---------------------------------------------------------------------------
  // Send helpers
  // ---------------------------------------------------------------------------
  function sendMessage(text) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!text.trim()) return;
    ws.send(JSON.stringify({ type: "message", text: text }));
    inputEl.value = "";
    autoResizeInput();
  }

  // ---------------------------------------------------------------------------
  // Event dispatcher
  // ---------------------------------------------------------------------------
  function handleEvent(ev) {
    switch (ev.type) {
      case "connected":
      case "session_started":
      case "session_resumed":
        onConnected(ev);
        break;
      case "system_message":
        appendMessage("system", ev.text);
        break;
      case "user_message":
        appendMessage("user", ev.text);
        break;
      case "assistant_message":
        appendMessage("assistant", ev.text);
        break;
      case "error":
        appendMessage("error", ev.text);
        break;
      case "status":
        statusEl.textContent = ev.text;
        break;
      case "processing_start":
        showIndicator(ev.label || "Thinking");
        break;
      case "processing_end":
        hideIndicator();
        break;
      case "stream_start":
        onStreamStart(ev);
        break;
      case "stream_delta":
        onStreamDelta(ev);
        break;
      case "stream_end":
        onStreamEnd(ev);
        break;
      case "tool_start":
        onToolStart(ev);
        break;
      case "tool_end":
        onToolEnd(ev);
        break;
      case "usage_update":
        onUsageUpdate(ev);
        break;
      case "clear":
        messagesEl.innerHTML = "";
        break;
      case "pong":
        break;
      case "session_list":
        renderSessionList(ev.sessions);
        break;
      default:
        console.log("Unknown event:", ev);
    }
  }

  // ---------------------------------------------------------------------------
  // Connection event
  // ---------------------------------------------------------------------------
  function onConnected(ev) {
    if (ev.model) {
      modelEl.textContent = ev.model;
    }
    if (ev.session_id) {
      statusEl.textContent = "Session: " + ev.session_id.substring(0, 8);
    }
  }

  // ---------------------------------------------------------------------------
  // Message rendering
  // ---------------------------------------------------------------------------
  function appendMessage(role, text) {
    var el = document.createElement("div");
    el.className = "message message-" + role;

    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = role === "user" ? "You"
                      : role === "assistant" ? "Assistant"
                      : role === "error" ? "Error"
                      : "System";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body";
    if (role === "user") {
      body.textContent = text;  // User messages stay plain text
    } else {
      body.innerHTML = renderMarkdown(text);  // Everything else renders markdown
    }
    el.appendChild(body);

    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function renderMarkdown(text) {
    try {
      var html = marked.parse(text);
      // Post-process: add copy buttons to code blocks
      var tmp = document.createElement("div");
      tmp.innerHTML = html;
      tmp.querySelectorAll("pre code").forEach(function (block) {
        hljs.highlightElement(block);
      });
      return tmp.innerHTML;
    } catch (_) {
      return escapeHtml(text);
    }
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ---------------------------------------------------------------------------
  // Streaming
  // ---------------------------------------------------------------------------
  function onStreamStart(ev) {
    var el = document.createElement("div");
    var blockClass = ev.block_type === "thinking" ? "message-thinking" : "message-assistant";
    el.className = "message " + blockClass;

    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = ev.block_type === "thinking" ? "Thinking" : "Assistant";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body streaming";
    el.appendChild(body);

    messagesEl.appendChild(el);
    currentStreamEl = body;
    scrollToBottom();
  }

  function onStreamDelta(ev) {
    if (!currentStreamEl) {
      // Late join — create the element
      onStreamStart(ev);
    }
    currentStreamEl.innerHTML = renderMarkdown(ev.text);
    scrollToBottom();
  }

  function onStreamEnd(ev) {
    if (currentStreamEl) {
      currentStreamEl.classList.remove("streaming");
      currentStreamEl.innerHTML = renderMarkdown(ev.text);
      currentStreamEl = null;
    } else {
      // No streaming element existed — render as complete message
      var role = ev.block_type === "thinking" ? "thinking" : "assistant";
      appendMessage(role, ev.text);
    }
    scrollToBottom();
  }

  // ---------------------------------------------------------------------------
  // Tool calls
  // ---------------------------------------------------------------------------
  function onToolStart(ev) {
    var el = document.createElement("div");
    el.className = "message message-tool";
    el.setAttribute("data-tool", ev.tool_name);

    var header = document.createElement("div");
    header.className = "tool-header";
    header.innerHTML = '<span class="tool-icon">&#9881;</span> <strong>' +
      escapeHtml(ev.tool_name) + '</strong> <span class="tool-status running">running...</span>';
    
    // Make it collapsible
    header.style.cursor = "pointer";
    header.addEventListener("click", function () {
      var detail = el.querySelector(".tool-detail");
      if (detail) {
        detail.classList.toggle("hidden");
      }
    });
    el.appendChild(header);

    // Tool input (collapsed by default)
    if (ev.tool_input && Object.keys(ev.tool_input).length > 0) {
      var detail = document.createElement("div");
      detail.className = "tool-detail hidden";
      var inputText = typeof ev.tool_input === "string"
        ? ev.tool_input
        : JSON.stringify(ev.tool_input, null, 2);
      detail.innerHTML = '<pre class="tool-input"><code>' +
        escapeHtml(inputText) + '</code></pre>';
      el.appendChild(detail);
    }

    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function onToolEnd(ev) {
    // Find the most recent matching tool element
    var tools = messagesEl.querySelectorAll('.message-tool[data-tool="' + ev.tool_name + '"]');
    var el = tools.length > 0 ? tools[tools.length - 1] : null;
    
    if (el) {
      var statusSpan = el.querySelector(".tool-status");
      if (statusSpan) {
        var failed = ev.result && ev.result.startsWith("Error");
        statusSpan.textContent = failed ? "failed" : "done";
        statusSpan.className = "tool-status " + (failed ? "failed" : "done");
      }
      // Add result to detail
      if (ev.result) {
        var detail = el.querySelector(".tool-detail");
        if (!detail) {
          detail = document.createElement("div");
          detail.className = "tool-detail hidden";
          el.appendChild(detail);
        }
        var resultEl = document.createElement("pre");
        resultEl.className = "tool-result";
        resultEl.textContent = ev.result.length > 500
          ? ev.result.substring(0, 500) + "..."
          : ev.result;
        detail.appendChild(resultEl);
      }
    }
    scrollToBottom();
  }

  // ---------------------------------------------------------------------------
  // Usage / tokens
  // ---------------------------------------------------------------------------
  function onUsageUpdate(ev) {
    if (ev.model) {
      modelEl.textContent = ev.model;
    }
    var inp = ev.input_tokens || 0;
    var out = ev.output_tokens || 0;
    tokenEl.textContent = formatTokens(inp) + " in / " + formatTokens(out) + " out";
  }

  function formatTokens(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "k";
    return String(n);
  }

  // ---------------------------------------------------------------------------
  // Indicator
  // ---------------------------------------------------------------------------
  function showIndicator(label) {
    indicatorEl.classList.remove("hidden");
    statusEl.textContent = label + "...";
    scrollToBottom();
  }

  function hideIndicator() {
    indicatorEl.classList.add("hidden");
    statusEl.textContent = "Ready";
  }

  // ---------------------------------------------------------------------------
  // Scroll
  // ---------------------------------------------------------------------------
  function scrollToBottom() {
    var chatArea = document.getElementById("chat-area");
    requestAnimationFrame(function () {
      chatArea.scrollTop = chatArea.scrollHeight;
    });
  }

  // ---------------------------------------------------------------------------
  // Command history (up/down arrow in input)
  // ---------------------------------------------------------------------------
  var cmdHistory = [];
  var cmdHistoryIdx = -1;
  var cmdDraft = "";

  function pushHistory(text) {
    if (text.trim() && (cmdHistory.length === 0 || cmdHistory[cmdHistory.length - 1] !== text)) {
      cmdHistory.push(text);
    }
    cmdHistoryIdx = -1;
    cmdDraft = "";
  }

  // ---------------------------------------------------------------------------
  // Slash-command completion
  // ---------------------------------------------------------------------------
  var knownCommands = [
    "/help", "/git", "/diff", "/tokens", "/agents", "/recipe", "/tools",
    "/compare", "/branch", "/branches", "/replay", "/dashboard", "/watch",
    "/plugins", "/shell", "/theme", "/stats", "/info", "/context", "/system",
    "/mode", "/modes", "/attach", "/cat", "/history", "/ref", "/refs",
    "/alias", "/snippet", "/snippets", "/template", "/templates", "/draft",
    "/drafts", "/note", "/notes", "/bookmark", "/bookmarks", "/tag", "/tags",
    "/pin", "/pins", "/new", "/clear", "/sessions", "/session", "/list",
    "/include", "/model", "/copy", "/undo", "/redo", "/retry", "/fork",
    "/keys", "/clipboard"
  ];

  function completeCommand(partial) {
    var lower = partial.toLowerCase();
    var matches = knownCommands.filter(function (c) { return c.indexOf(lower) === 0; });
    return matches;
  }

  // ---------------------------------------------------------------------------
  // Input handling
  // ---------------------------------------------------------------------------
  inputEl.addEventListener("keydown", function (e) {
    // Enter → send (Shift+Enter → newline)
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      var text = inputEl.value;
      if (text.trim()) {
        pushHistory(text);
        sendMessage(text);
      }
      return;
    }

    // Tab → slash-command completion
    if (e.key === "Tab" && inputEl.value.startsWith("/")) {
      e.preventDefault();
      var matches = completeCommand(inputEl.value);
      if (matches.length === 1) {
        inputEl.value = matches[0] + " ";
      } else if (matches.length > 1) {
        appendMessage("system", "Completions: " + matches.join(", "));
      }
      return;
    }

    // Up/Down → command history
    if (e.key === "ArrowUp" && inputEl.selectionStart === 0) {
      e.preventDefault();
      if (cmdHistoryIdx === -1) {
        cmdDraft = inputEl.value;
        cmdHistoryIdx = cmdHistory.length - 1;
      } else if (cmdHistoryIdx > 0) {
        cmdHistoryIdx--;
      }
      if (cmdHistoryIdx >= 0) inputEl.value = cmdHistory[cmdHistoryIdx];
      return;
    }
    if (e.key === "ArrowDown" && cmdHistoryIdx >= 0) {
      e.preventDefault();
      cmdHistoryIdx++;
      if (cmdHistoryIdx >= cmdHistory.length) {
        cmdHistoryIdx = -1;
        inputEl.value = cmdDraft;
      } else {
        inputEl.value = cmdHistory[cmdHistoryIdx];
      }
      return;
    }

    // Escape → clear input / cancel streaming
    if (e.key === "Escape") {
      if (inputEl.value) {
        inputEl.value = "";
        autoResizeInput();
      } else if (currentStreamEl) {
        // Cancel streaming (TODO: send cancel event)
        appendMessage("system", "Cancel not yet implemented");
      }
      return;
    }
  });

  sendBtn.addEventListener("click", function () {
    var text = inputEl.value;
    if (text.trim()) {
      pushHistory(text);
      sendMessage(text);
    }
  });

  // ---------------------------------------------------------------------------
  // Sidebar
  // ---------------------------------------------------------------------------
  function toggleSidebar() {
    sidebarEl.classList.toggle("hidden");
    // Fetch session list when opening
    if (!sidebarEl.classList.contains("hidden")) {
      fetchSessionList();
    }
  }

  function fetchSessionList() {
    fetch("/api/sessions")
      .then(function(r) { return r.json(); })
      .then(function(data) { renderSessionList(data.sessions || data); })
      .catch(function(err) { console.error("Failed to fetch sessions:", err); });
  }

  function renderSessionList(sessions) {
    sessionListEl.innerHTML = "";
    if (!sessions || sessions.length === 0) {
      sessionListEl.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:13px;">No sessions yet</div>';
      return;
    }
    sessions.forEach(function(s) {
      var item = document.createElement("div");
      item.className = "session-item" + (s.active ? " active" : "");
      item.innerHTML = '<div class="session-item-title">' + escapeHtml(s.title || s.id || "Untitled") + '</div>'
                     + '<div class="session-item-date">' + escapeHtml(s.date || "") + '</div>';
      item.addEventListener("click", function() {
        sendRaw({ type: "switch_session", id: s.id });
      });
      sessionListEl.appendChild(item);
    });
  }

  function sendRaw(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  if (sidebarToggleEl) sidebarToggleEl.addEventListener("click", toggleSidebar);
  if (newSessionBtn) newSessionBtn.addEventListener("click", function() {
    sendMessage("/new");
    toggleSidebar();
  });
  if (sidebarCloseBtn) sidebarCloseBtn.addEventListener("click", toggleSidebar);

  // ── Command Palette ──
  var commandPalette = [
    { name: "New Session",     cmd: "/new",        keys: "",              cat: "session",  desc: "Start a new chat session" },
    { name: "Clear Chat",      cmd: "/clear",      keys: "",              cat: "session",  desc: "Clear the chat display" },
    { name: "Sessions",        cmd: "/sessions",   keys: "",              cat: "session",  desc: "List all sessions" },
    { name: "Resume Session",  cmd: "/resume",     keys: "",              cat: "session",  desc: "Resume a previous session" },
    { name: "Git Status",      cmd: "/git",        keys: "",              cat: "git",      desc: "Show git status" },
    { name: "Git Diff",        cmd: "/diff",       keys: "",              cat: "git",      desc: "Show git diff" },
    { name: "Token Usage",     cmd: "/tokens",     keys: "",              cat: "info",     desc: "Show token usage and cost" },
    { name: "Statistics",      cmd: "/stats",      keys: "",              cat: "info",     desc: "Show session statistics" },
    { name: "Model Info",      cmd: "/model",      keys: "",              cat: "info",     desc: "Show or switch LLM model" },
    { name: "Dashboard",       cmd: "/dashboard",  keys: "",              cat: "info",     desc: "Show session dashboard" },
    { name: "Context",         cmd: "/context",    keys: "",              cat: "info",     desc: "Show context information" },
    { name: "Agents",          cmd: "/agents",     keys: "",              cat: "ai",       desc: "List active agents" },
    { name: "Tools",           cmd: "/tools",      keys: "",              cat: "ai",       desc: "List available tools" },
    { name: "Recipe",          cmd: "/recipe",     keys: "",              cat: "ai",       desc: "Manage recipes" },
    { name: "System Prompt",   cmd: "/system",     keys: "",              cat: "config",   desc: "View or set system prompt" },
    { name: "Mode",            cmd: "/mode",       keys: "",              cat: "config",   desc: "Switch operational mode" },
    { name: "Theme",           cmd: "/theme",      keys: "",              cat: "config",   desc: "Change color theme" },
    { name: "Help",            cmd: "/help",       keys: "",              cat: "info",     desc: "Show available commands" },
    { name: "Toggle Sidebar",  cmd: null,          keys: "",              cat: "ui",       desc: "Show/hide session sidebar", action: "toggle-sidebar" },
  ];

  var paletteSelectedIdx = -1;

  function openPalette() {
    paletteOverlay.classList.remove("hidden");
    paletteInput.value = "";
    paletteSelectedIdx = -1;
    renderPaletteResults("");
    setTimeout(function() { paletteInput.focus(); }, 10);
  }

  function closePalette() {
    paletteOverlay.classList.add("hidden");
    paletteInput.value = "";
    inputEl.focus();
  }

  function renderPaletteResults(query) {
    var q = query.toLowerCase().trim();
    var filtered = commandPalette.filter(function(c) {
      if (!q) return true;
      return c.name.toLowerCase().indexOf(q) !== -1
          || (c.cmd && c.cmd.toLowerCase().indexOf(q) !== -1)
          || c.desc.toLowerCase().indexOf(q) !== -1
          || c.cat.toLowerCase().indexOf(q) !== -1;
    });

    paletteResults.innerHTML = "";
    if (filtered.length === 0) {
      paletteResults.innerHTML = '<div style="padding:12px 16px;color:var(--text-muted);font-size:13px;">No matching commands</div>';
      return;
    }

    // Group by category
    var groups = {};
    filtered.forEach(function(c) {
      if (!groups[c.cat]) groups[c.cat] = [];
      groups[c.cat].push(c);
    });

    var idx = 0;
    Object.keys(groups).forEach(function(cat) {
      var catLabel = document.createElement("div");
      catLabel.className = "palette-category";
      catLabel.textContent = cat;
      paletteResults.appendChild(catLabel);

      groups[cat].forEach(function(c) {
        var item = document.createElement("div");
        item.className = "palette-item" + (idx === paletteSelectedIdx ? " selected" : "");
        item.setAttribute("data-idx", idx);
        item.innerHTML = '<div class="palette-item-left">'
          + '<div class="palette-item-name">' + escapeHtml(c.name) + '</div>'
          + '<div class="palette-item-desc">' + escapeHtml(c.desc) + '</div>'
          + '</div>'
          + '<div class="palette-item-right">'
          + (c.cmd ? '<span class="palette-item-cmd">' + escapeHtml(c.cmd) + '</span>' : '')
          + (c.keys ? '<span class="palette-item-keys">' + escapeHtml(c.keys) + '</span>' : '')
          + '</div>';
        item.addEventListener("click", function() { executePaletteItem(c); });
        paletteResults.appendChild(item);
        idx++;
      });
    });

    // Auto-select first if nothing selected
    if (paletteSelectedIdx < 0 && filtered.length > 0) {
      paletteSelectedIdx = 0;
      updatePaletteSelection();
    }
  }

  function updatePaletteSelection() {
    var items = paletteResults.querySelectorAll(".palette-item");
    items.forEach(function(el, i) {
      el.classList.toggle("selected", i === paletteSelectedIdx);
    });
    // Scroll selected into view
    if (items[paletteSelectedIdx]) {
      items[paletteSelectedIdx].scrollIntoView({ block: "nearest" });
    }
  }

  function executePaletteItem(c) {
    closePalette();
    if (c.action === "toggle-sidebar") {
      toggleSidebar();
    } else if (c.cmd) {
      sendMessage(c.cmd);
    }
  }

  function getFilteredPaletteItems() {
    var q = (paletteInput.value || "").toLowerCase().trim();
    return commandPalette.filter(function(c) {
      if (!q) return true;
      return c.name.toLowerCase().indexOf(q) !== -1
          || (c.cmd && c.cmd.toLowerCase().indexOf(q) !== -1)
          || c.desc.toLowerCase().indexOf(q) !== -1
          || c.cat.toLowerCase().indexOf(q) !== -1;
    });
  }

  if (paletteInput) {
    paletteInput.addEventListener("input", function() {
      paletteSelectedIdx = 0;
      renderPaletteResults(paletteInput.value);
    });

    paletteInput.addEventListener("keydown", function(e) {
      var items = getFilteredPaletteItems();
      if (e.key === "ArrowDown") {
        e.preventDefault();
        paletteSelectedIdx = Math.min(paletteSelectedIdx + 1, items.length - 1);
        updatePaletteSelection();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        paletteSelectedIdx = Math.max(paletteSelectedIdx - 1, 0);
        updatePaletteSelection();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (items[paletteSelectedIdx]) {
          executePaletteItem(items[paletteSelectedIdx]);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        closePalette();
      }
    });
  }

  // Close palette on backdrop click
  if (paletteOverlay) {
    paletteOverlay.addEventListener("click", function(e) {
      if (e.target === paletteOverlay) closePalette();
    });
  }

  // ---------------------------------------------------------------------------
  // Global keyboard shortcuts (browser-safe, no Ctrl+B/H/T conflicts)
  // ---------------------------------------------------------------------------
  document.addEventListener("keydown", function (e) {
    // Command palette: Ctrl+K or Cmd+K
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      if (paletteOverlay.classList.contains("hidden")) {
        openPalette();
      } else {
        closePalette();
      }
      return;
    }

    // Don't intercept when typing in input (unless it's a global shortcut)
    var inInput = document.activeElement === inputEl;

    // Ctrl+L or Cmd+L → focus input (like address bar, but for chat)
    if ((e.ctrlKey || e.metaKey) && e.key === "l") {
      e.preventDefault();
      inputEl.focus();
      inputEl.select();
      return;
    }

    // Ctrl+/ or Cmd+/ → show help
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      sendMessage("/help");
      return;
    }

    // Ctrl+Shift+N → new session
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "N") {
      e.preventDefault();
      sendMessage("/new");
      return;
    }

    // Ctrl+Shift+S → session list
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "S") {
      e.preventDefault();
      sendMessage("/sessions");
      return;
    }

    // Ctrl+Shift+K → clear chat
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "K") {
      e.preventDefault();
      sendMessage("/clear");
      return;
    }

    // Ctrl+Shift+G → git status
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "G") {
      e.preventDefault();
      sendMessage("/git");
      return;
    }

    // Ctrl+Shift+T → token info
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "T") {
      e.preventDefault();
      sendMessage("/tokens");
      return;
    }

    // Ctrl+Shift+D → dashboard
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "D") {
      e.preventDefault();
      sendMessage("/dashboard");
      return;
    }

    // / → focus input and start command (when not already in input)
    if (!inInput && e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      inputEl.focus();
      inputEl.value = "/";
      autoResizeInput();
      return;
    }
  });

  // Auto-resize textarea
  function autoResizeInput() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + "px";
  }
  inputEl.addEventListener("input", autoResizeInput);

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  connect();
  inputEl.focus();
})();
