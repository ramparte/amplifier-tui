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
    if (role === "assistant") {
      body.innerHTML = renderMarkdown(text);
    } else {
      body.textContent = text;
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
  // Input handling
  // ---------------------------------------------------------------------------
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputEl.value);
    }
  });

  sendBtn.addEventListener("click", function () {
    sendMessage(inputEl.value);
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
})();
