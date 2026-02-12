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
      case "stats_panel":
        renderStatsPanel(ev);
        break;
      case "token_usage":
        renderTokenUsage(ev);
        break;
      case "agent_tree":
        renderAgentTree(ev);
        break;
      case "git_status":
        renderGitStatus(ev);
        break;
      case "dashboard":
        renderDashboard(ev);
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
      document.title = "Amplifier - " + ev.session_id.substring(0, 8);
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
      var tmp = document.createElement("div");
      tmp.innerHTML = html;
      tmp.querySelectorAll("pre code").forEach(function (block) {
        hljs.highlightElement(block);
        // Add copy button
        var pre = block.parentNode;
        pre.style.position = "relative";
        var btn = document.createElement("button");
        btn.className = "code-copy-btn";
        btn.textContent = "Copy";
        btn.addEventListener("click", function() {
          navigator.clipboard.writeText(block.textContent).then(function() {
            btn.textContent = "Copied!";
            setTimeout(function() { btn.textContent = "Copy"; }, 2000);
          });
        });
        pre.appendChild(btn);
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
  // Structured card renderers
  // ---------------------------------------------------------------------------

  function renderStatsPanel(ev) {
    var el = document.createElement("div");
    el.className = "message message-system";
    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = "Session Statistics";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body structured-card stats-card";
    var html = '<div class="card-grid">'
      + '<div class="card-stat"><div class="card-stat-value">' + escapeHtml(ev.duration || "\u2014") + '</div><div class="card-stat-label">Duration</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + (ev.messages || 0) + '</div><div class="card-stat-label">Messages</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + formatTokens(ev.total_tokens || 0) + '</div><div class="card-stat-label">Tokens</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + (ev.tool_calls || 0) + '</div><div class="card-stat-label">Tool Calls</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + escapeHtml(ev.model || "\u2014") + '</div><div class="card-stat-label">Model</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + escapeHtml(ev.cost || "\u2014") + '</div><div class="card-stat-label">Est. Cost</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + escapeHtml(ev.avg_response_time || "\u2014") + '</div><div class="card-stat-label">Avg Response</div></div>'
      + '</div>';

    // Token breakdown
    var inp = ev.input_tokens || 0;
    var out = ev.output_tokens || 0;
    html += '<div class="card-detail-row"><span class="card-detail-label">Tokens:</span> '
      + '<span class="card-detail-value">' + formatTokens(inp) + ' in / ' + formatTokens(out) + ' out</span></div>';

    // Top tools
    if (ev.top_tools && ev.top_tools.length > 0) {
      html += '<div class="card-detail-row"><span class="card-detail-label">Top Tools:</span> '
        + '<span class="card-detail-value">'
        + ev.top_tools.map(function (t) { return escapeHtml(t.name) + " (" + t.count + ")"; }).join(", ")
        + '</span></div>';
    }

    body.innerHTML = html;
    el.appendChild(body);
    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function renderTokenUsage(ev) {
    var el = document.createElement("div");
    el.className = "message message-system";
    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = "Token Usage";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body structured-card token-card";
    var inp = ev.input_tokens || 0;
    var out = ev.output_tokens || 0;
    var total = ev.total_tokens || 0;
    var window = ev.context_window || 200000;
    var pct = ev.usage_pct || 0;
    var maxBar = inp + out || 1;

    var html = '<div class="card-detail-row" style="margin-bottom:4px">'
      + '<span class="card-detail-label">Model:</span> '
      + '<span class="card-detail-value" style="color:var(--text-accent)">' + escapeHtml(ev.model || "\u2014") + '</span></div>';

    // Input bar
    html += '<div class="token-row"><span class="token-row-label">Input</span>'
      + '<div class="token-bar"><div class="token-bar-fill token-bar-input" style="width:' + Math.round(inp / maxBar * 100) + '%"></div></div>'
      + '<span class="token-row-value">' + formatTokens(inp) + '</span></div>';

    // Output bar
    html += '<div class="token-row"><span class="token-row-label">Output</span>'
      + '<div class="token-bar"><div class="token-bar-fill token-bar-output" style="width:' + Math.round(out / maxBar * 100) + '%"></div></div>'
      + '<span class="token-row-value">' + formatTokens(out) + '</span></div>';

    // Context usage bar
    html += '<div class="token-row" style="margin-top:8px"><span class="token-row-label">Context</span>'
      + '<div class="token-bar"><div class="token-bar-fill token-bar-context" style="width:' + Math.min(pct, 100) + '%"></div></div>'
      + '<span class="token-row-value">' + pct + '%</span></div>';

    // Summary line
    html += '<div class="card-detail-row" style="margin-top:8px">'
      + '<span class="card-detail-label">Total:</span> '
      + '<span class="card-detail-value">' + formatTokens(total) + ' / ' + formatTokens(window) + '</span>'
      + ' &nbsp; <span class="card-detail-label">Cost:</span> '
      + '<span class="card-detail-value">' + escapeHtml(ev.cost || "\u2014") + '</span></div>';

    body.innerHTML = html;
    el.appendChild(body);
    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function renderAgentTree(ev) {
    var el = document.createElement("div");
    el.className = "message message-system";
    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = "Agent Delegations";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body structured-card agent-card";
    var agents = ev.agents || [];

    if (agents.length === 0) {
      body.innerHTML = '<div class="card-empty">No agent delegations in this session.</div>';
    } else {
      var html = '';
      for (var i = 0; i < agents.length; i++) {
        var a = agents[i];
        var statusClass = a.status === "running" ? "running"
                        : a.status === "completed" ? "done"
                        : a.status === "failed" ? "failed" : "";
        var statusIcon = a.status === "running" ? "\u27f3"
                       : a.status === "completed" ? "\u2713"
                       : a.status === "failed" ? "\u2717" : "?";
        html += '<div class="agent-item ' + statusClass + '">'
          + '<span class="agent-status-icon">' + statusIcon + '</span> '
          + '<span class="agent-name">' + escapeHtml(a.name) + '</span>'
          + '<span class="agent-elapsed">' + escapeHtml(a.elapsed || "") + '</span>'
          + '<div class="agent-instruction">' + escapeHtml(a.instruction || "") + '</div>'
          + '</div>';
      }
      // Summary
      var parts = [];
      if (ev.total) parts.push(ev.total + " total");
      if (ev.running) parts.push(ev.running + " running");
      if (ev.completed) parts.push(ev.completed + " completed");
      if (ev.failed) parts.push(ev.failed + " failed");
      if (parts.length) {
        html += '<div class="agent-summary">' + parts.join(" \u00b7 ") + '</div>';
      }
      body.innerHTML = html;
    }

    el.appendChild(body);
    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function renderGitStatus(ev) {
    var el = document.createElement("div");
    el.className = "message message-system";
    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = "Git Status";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body structured-card git-card";

    var html = '<div class="git-branch">\ud83c\udf3f ' + escapeHtml(ev.branch || "unknown") + '</div>';

    if (ev.clean) {
      html += '<div class="git-clean">\u2713 Clean working tree</div>';
    } else {
      html += '<div class="git-changes">';
      if (ev.staged) {
        html += '<span class="git-badge git-staged">' + ev.staged + ' staged</span>';
      }
      if (ev.modified) {
        html += '<span class="git-badge git-modified">' + ev.modified + ' modified</span>';
      }
      if (ev.untracked) {
        html += '<span class="git-badge git-untracked">' + ev.untracked + ' untracked</span>';
      }
      html += '</div>';
    }

    if (ev.ahead || ev.behind) {
      html += '<div class="git-sync">';
      if (ev.ahead) html += '<span class="git-ahead">\u2191 ' + ev.ahead + ' ahead</span>';
      if (ev.behind) html += '<span class="git-behind">\u2193 ' + ev.behind + ' behind</span>';
      html += '</div>';
    }

    if (ev.last_commit) {
      html += '<div class="git-last-commit">Last: ' + escapeHtml(ev.last_commit) + '</div>';
    }

    body.innerHTML = html;
    el.appendChild(body);
    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function renderDashboard(ev) {
    var el = document.createElement("div");
    el.className = "message message-system";
    var label = document.createElement("div");
    label.className = "message-label";
    label.textContent = "Dashboard";
    el.appendChild(label);

    var body = document.createElement("div");
    body.className = "message-body structured-card dashboard-card";

    var html = '<div class="card-grid">'
      + '<div class="card-stat"><div class="card-stat-value">' + (ev.total_sessions || 0) + '</div><div class="card-stat-label">Sessions</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + formatTokens(ev.total_tokens || 0) + '</div><div class="card-stat-label">Total Tokens</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + escapeHtml(ev.total_duration || "\u2014") + '</div><div class="card-stat-label">Total Time</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + escapeHtml(ev.avg_duration || "\u2014") + '</div><div class="card-stat-label">Avg Session</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + (ev.streak_days || 0) + '</div><div class="card-stat-label">Current Streak</div></div>'
      + '<div class="card-stat"><div class="card-stat-value">' + (ev.longest_streak || 0) + '</div><div class="card-stat-label">Longest Streak</div></div>'
      + '</div>';

    // Top models
    if (ev.top_models && ev.top_models.length > 0) {
      html += '<div class="card-detail-row"><span class="card-detail-label">Models:</span> '
        + '<span class="card-detail-value">'
        + ev.top_models.map(function (m) { return escapeHtml(m.name) + " (" + m.count + ")"; }).join(", ")
        + '</span></div>';
    }

    // Top projects
    if (ev.top_projects && ev.top_projects.length > 0) {
      html += '<div class="card-detail-row"><span class="card-detail-label">Projects:</span> '
        + '<span class="card-detail-value">'
        + ev.top_projects.map(function (p) { return escapeHtml(p.name) + " (" + p.count + ")"; }).join(", ")
        + '</span></div>';
    }

    body.innerHTML = html;
    el.appendChild(body);
    messagesEl.appendChild(el);
    scrollToBottom();
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
  // Slash-command hints popup
  // ---------------------------------------------------------------------------
  var SLASH_COMMANDS = [
    { cmd: '/help',      desc: 'Show help information' },
    { cmd: '/stats',     desc: 'Session statistics' },
    { cmd: '/tokens',    desc: 'Token usage details' },
    { cmd: '/agents',    desc: 'Available agents' },
    { cmd: '/git',       desc: 'Git repository status' },
    { cmd: '/dashboard', desc: 'Session dashboard' },
    { cmd: '/clear',     desc: 'Clear conversation' },
    { cmd: '/sessions',  desc: 'List sessions' },
  ];

  function showSlashHints() {
    var hints = document.getElementById('slash-hints');
    if (!hints) return;
    var list = hints.querySelector('.slash-hints-list');
    list.innerHTML = SLASH_COMMANDS.map(function(c) {
      return '<div class="slash-hint-item" role="option" data-cmd="' + c.cmd + '">'
        + '<span class="hint-cmd">' + c.cmd + '</span>'
        + '<span class="hint-desc">' + c.desc + '</span>'
        + '</div>';
    }).join('');
    // Click handler for each hint
    list.querySelectorAll('.slash-hint-item').forEach(function(item) {
      item.addEventListener('click', function() {
        if (inputEl) {
          inputEl.value = item.dataset.cmd;
          inputEl.focus();
        }
        hideSlashHints();
      });
    });
    hints.hidden = false;
  }

  function hideSlashHints() {
    var hints = document.getElementById('slash-hints');
    if (hints) hints.hidden = true;
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
      hideSlashHints();
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
    hideSlashHints();
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
      item.setAttribute("role", "option");
      item.setAttribute("aria-label", s.title || s.id || "Untitled session");
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
        item.setAttribute("role", "option");
        item.setAttribute("aria-label", c.name + (c.cmd ? " " + c.cmd : ""));
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
  // Global keyboard shortcuts (web-safe, minimal — palette handles the rest)
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

    // Focus input: Ctrl+L
    if (e.ctrlKey && e.key === "l") {
      e.preventDefault();
      inputEl.focus();
      return;
    }

    // Slash shortcut: "/" when not in input focuses input with "/"
    if (e.key === "/" && document.activeElement !== inputEl && document.activeElement !== paletteInput) {
      e.preventDefault();
      inputEl.focus();
      inputEl.value = "/";
      autoResizeInput();
      showSlashHints();
      return;
    }

    // Escape: close slash hints, palette, sidebar, or blur input
    if (e.key === "Escape") {
      var slashHintsEl = document.getElementById('slash-hints');
      if (slashHintsEl && !slashHintsEl.hidden) {
        hideSlashHints();
      } else if (!paletteOverlay.classList.contains("hidden")) {
        closePalette();
      } else if (!sidebarEl.classList.contains("hidden")) {
        toggleSidebar();
      } else if (document.activeElement === inputEl) {
        inputEl.blur();
      }
      return;
    }
  });

  // Auto-resize textarea
  function autoResizeInput() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + "px";
  }
  inputEl.addEventListener("input", function() {
    autoResizeInput();
    // Dismiss slash hints when input no longer starts with "/"
    if (!inputEl.value.startsWith("/")) {
      hideSlashHints();
    }
  });

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  connect();
  inputEl.focus();
})();
