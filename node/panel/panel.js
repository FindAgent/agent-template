"use strict";
/*
 * Crate check result panel.
 *
 * One self-contained document. It makes no network request, calls no tool and builds every node
 * with createElement + textContent (never innerHTML), so any string in a result (a crate name,
 * a yank message) is inert data. The tool result arrives from the host over the MCP Apps
 * postMessage bridge. Anything the person wants done goes back to the conversation as a
 * `ui/message`, never as a tool call: a creator's panel may not call tools on any host.
 */
(function () {
  var root = document.getElementById("root");

  // ---- tiny DOM helpers ---------------------------------------------------------------------
  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) {
      if (arguments[i]) parent.appendChild(arguments[i]);
    }
    return parent;
  }
  function str(v) {
    return v == null ? "" : String(v);
  }
  function list(v) {
    return Array.isArray(v) ? v : [];
  }

  // ---- host bridge (MCP Apps) ---------------------------------------------------------------
  var rpcId = 1;
  var initId = 0;
  var pending = {};

  function post(msg) {
    try {
      window.parent.postMessage(msg, "*");
    } catch (e) {
      /* no host to talk to */
    }
  }
  function notify(method, params) {
    post({ jsonrpc: "2.0", method: method, params: params || {} });
  }
  /** Send a request and resolve { ok, result } or { ok: false, reason }. Never rejects. */
  function request(method, params, timeoutMs) {
    return new Promise(function (resolve) {
      var id = rpcId++;
      var done = false;
      function finish(res) {
        if (done) return;
        done = true;
        clearTimeout(pending[id].timer);
        delete pending[id];
        resolve(res);
      }
      pending[id] = { finish: finish };
      pending[id].timer = setTimeout(function () {
        finish({ ok: false, reason: "timeout" });
      }, timeoutMs);
      post({ jsonrpc: "2.0", id: id, method: method, params: params });
    });
  }

  // The height reported is the CONTENT height. documentElement.scrollHeight is never smaller than
  // the frame the host has already grown, so a panel that reported it could never shrink again.
  var lastW = 0;
  var lastH = 0;
  function reportSize() {
    var b = document.body;
    if (!b) return;
    var height = Math.ceil(b.getBoundingClientRect().height);
    var width = Math.ceil(b.scrollWidth);
    if (!height || (height === lastH && width === lastW)) return;
    lastW = width;
    lastH = height;
    notify("ui/notifications/size-changed", { width: width, height: height });
  }
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(reportSize).observe(document.body);
  window.addEventListener("load", reportSize);

  // ---- hand a request to the conversation ---------------------------------------------------
  var statusEl = null;
  var fallbackEl = null;

  function say(text) {
    if (statusEl) statusEl.textContent = text;
    reportSize();
  }

  function showFallback(text) {
    var box = h("p", "pc-fallback pc-code", text);
    box.setAttribute("tabindex", "0");
    if (fallbackEl && fallbackEl.parentNode) fallbackEl.parentNode.replaceChild(box, fallbackEl);
    else if (statusEl && statusEl.parentNode)
      statusEl.parentNode.insertBefore(box, statusEl.nextSibling);
    fallbackEl = box;
    reportSize();
  }

  /** A button that posts `prompt` to the conversation. If the host refuses, the text is shown to copy. */
  function askButton(label, prompt) {
    var b = h("button", null, label);
    b.type = "button";
    b.addEventListener("click", function () {
      b.disabled = true;
      say("Sending to the conversation...");
      request("ui/message", { role: "user", content: { type: "text", text: prompt } }, 6000).then(
        function (res) {
          b.disabled = false;
          if (res && res.ok) {
            say("Sent. The assistant will take it from here.");
          } else {
            say("This host did not take the message. Copy it into the chat:");
            showFallback(prompt);
          }
        },
      );
    });
    return b;
  }

  // ---- pieces -------------------------------------------------------------------------------
  var STATUS = {
    ok: { label: "OK", tone: "good" },
    warn: { label: "Warn", tone: "warn" },
    risk: { label: "Risk", tone: "bad" },
    not_checked: { label: "Not checked", tone: "mute" },
  };
  var VERDICT = {
    healthy: { label: "Healthy", tone: "good" },
    watch: { label: "Watch", tone: "warn" },
    risky: { label: "Risky", tone: "bad" },
    unknown: { label: "Unknown", tone: "mute" },
  };
  var FAILURE = {
    invalid_input: "That is not a valid crate name",
    not_found: "Crate not found",
    rate_limited: "Rate limited",
    timeout: "crates.io did not answer in time",
    network_error: "Could not reach crates.io",
    upstream_error: "crates.io returned an error",
    malformed_response: "The crates.io answer could not be read",
    response_too_large: "The crates.io answer was too large",
  };

  function chip(text, tone) {
    return h("span", "pc-chip " + tone, text);
  }

  function card(title) {
    var c = h("section", "pc-card");
    if (title) add(c, h("h2", null, title));
    return c;
  }

  function header(titleText) {
    var head = h("div", "pc-head");
    add(head, h("h1", "pc-pkg", titleText));
    return head;
  }

  /** The status line every renderer ends with; a button writes to it. */
  function actionsRow(button) {
    var row = h("div", "pc-actions");
    statusEl = h("p", "pc-status");
    statusEl.setAttribute("role", "status");
    add(row, button, statusEl);
    return row;
  }

  // ---- views --------------------------------------------------------------------------------
  function renderReport(r) {
    var frag = document.createDocumentFragment();
    add(frag, header(str(r.crate) + (r.version ? "@" + str(r.version) : "")));

    var v = VERDICT[r.verdict] || VERDICT.unknown;
    var top = card(null);
    var vrow = h("div", "pc-verdict");
    add(vrow, chip(v.label, v.tone), h("span", null, str(r.verdictReason)));
    add(top, vrow, h("p", "pc-sub", str(r.summary)));
    add(frag, top);

    var sig = card("Signals");
    var ul = h("ul", "pc-signals");
    list(r.signals).forEach(function (s) {
      var st = STATUS[s.status] || STATUS.not_checked;
      var li = h("li");
      var d = h("details");
      var sum = h("summary");
      add(sum, h("span", "pc-name", str(s.label)), chip(st.label, st.tone));
      var body = h("div", "pc-body");
      add(body, h("p", null, str(s.detail)), h("p", "pc-code", "source: " + str(s.source)));
      add(d, sum, body);
      add(li, d);
      add(ul, li);
    });
    add(sig, ul);
    add(frag, sig);

    var ask = card(null);
    add(
      ask,
      actionsRow(
        askButton(
          "Ask what to do about this",
          "Based on the check of " +
            str(r.crate) +
            " (verdict: " +
            str(r.verdict) +
            "), what should I do before depending on it?",
        ),
      ),
    );
    add(frag, ask);

    var req = r.requests || {};
    add(
      frag,
      h(
        "p",
        "pc-foot",
        "Checked " +
          str(r.checkedAt) +
          " using " +
          str(req.used) +
          " of " +
          str(req.budget) +
          " allowed requests. " +
          str(r.method),
      ),
    );
    return frag;
  }

  function renderFailure(f) {
    var frag = document.createDocumentFragment();
    add(frag, header(f.crate ? str(f.crate) : "Crate check"));
    var c = card(null);
    var row = h("div", "pc-verdict");
    add(row, chip(FAILURE[f.failure] || "The check failed", "bad"));
    add(c, row, h("p", null, str(f.message)));
    if (f.resetsAt) add(c, h("p", "pc-sub", "Try again after " + str(f.resetsAt) + "."));
    add(frag, c);
    return frag;
  }

  function renderNeedsInput(p) {
    var frag = document.createDocumentFragment();
    add(frag, header("More information needed"));
    var c = card(null);
    add(c, h("p", null, str(p.brief || p.restated_goal || "Answer these in the chat:")));
    var ol = h("ol", "pc-questions");
    list(p.questions).forEach(function (q) {
      add(ol, h("li", null, str(q.question)));
    });
    add(c, ol, h("p", "pc-sub", "Answer in the chat and the assistant will run the check."));
    add(frag, c);
    return frag;
  }

  function renderCapabilities(p) {
    var frag = document.createDocumentFragment();
    add(frag, header("What this agent checks"));
    var c = card("Signals");
    var ul = h("ul", "pc-signals");
    list(p.signals).forEach(function (s) {
      var li = h("li");
      var body = h("div", "pc-body");
      add(body, h("p", null, str(s.id) + ": " + str(s.rule)), h("p", "pc-code", str(s.field)));
      add(li, body);
      add(ul, li);
    });
    add(c, ul);
    add(frag, c, h("p", "pc-foot", str(p.data_source)));
    return frag;
  }

  function renderText(text) {
    var frag = document.createDocumentFragment();
    add(frag, header("Crate check"));
    add(frag, card(null)).appendChild(h("p", null, text));
    return frag;
  }

  // ---- routing a tool result ----------------------------------------------------------------
  function payloadFrom(result) {
    if (!result || typeof result !== "object") return null;
    if (result.structuredContent && typeof result.structuredContent === "object")
      return result.structuredContent;
    var content = result.content;
    if (Array.isArray(content)) {
      for (var i = 0; i < content.length; i++) {
        var b = content[i];
        if (b && b.type === "text" && typeof b.text === "string") {
          try {
            var parsed = JSON.parse(b.text);
            if (parsed && typeof parsed === "object") return parsed;
          } catch (e) {
            /* plain text */
          }
        }
      }
    }
    return null;
  }
  function textFrom(result) {
    var content = result && result.content;
    if (!Array.isArray(content)) return "";
    for (var i = 0; i < content.length; i++) {
      var b = content[i];
      if (b && b.type === "text" && typeof b.text === "string" && b.text.trim())
        return b.text.trim();
    }
    return "";
  }

  function show(node) {
    root.textContent = "";
    root.appendChild(node);
    reportSize();
  }

  function handleResult(result) {
    // Clear the previous view's handles BEFORE rendering: a renderer creates its own status line.
    statusEl = null;
    fallbackEl = null;
    var p = payloadFrom(result);
    if (p && p.kind === "crate_check") return show(renderReport(p));
    if (p && p.kind === "crate_failure") return show(renderFailure(p));
    if (p && (p.status === "needs_input" || p.status === "intent_discovery"))
      return show(renderNeedsInput(p));
    if (p && p.kind === "capabilities") return show(renderCapabilities(p));
    var t = textFrom(result);
    if (result && result.isError) {
      return show(
        renderFailure({ crate: "", failure: "error", message: t || "The check failed." }),
      );
    }
    show(renderText(t || "This result has no panel view."));
  }

  // ---- connect ------------------------------------------------------------------------------
  window.addEventListener("message", function (ev) {
    // Only the host speaks on this channel; a sibling frame cannot forge a result.
    if (ev.source !== window.parent) return;
    var msg = ev.data;
    if (!msg || typeof msg !== "object") return;
    if (msg.method === "ui/notifications/tool-result") {
      handleResult(msg.params);
      return;
    }
    if (msg.id != null && pending[msg.id]) {
      pending[msg.id].finish(
        msg.error ? { ok: false, reason: "host-error" } : { ok: true, result: msg.result },
      );
      return;
    }
    if (msg.id != null && msg.id === initId && (msg.result || msg.error)) {
      notify("ui/notifications/initialized", {});
    }
  });

  initId = rpcId++;
  post({ jsonrpc: "2.0", id: initId, method: "ui/initialize", params: { capabilities: {} } });
  setTimeout(function () {
    var st = document.getElementById("state");
    if (st) st.textContent = "Waiting for a result from the assistant...";
  }, 1500);
})();
