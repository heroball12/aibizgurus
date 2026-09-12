(() => {
  "use strict";
  const app = document.getElementById("demoApp");
  if (!app) return;
  const scenarios = JSON.parse(document.getElementById("demo-scenarios").textContent);
  const $ = id => document.getElementById(id);
  const chatHistory = JSON.parse($("demo-history").textContent);
  const tabs = [...document.querySelectorAll("[data-scenario]")];
  const steps = [...document.querySelectorAll("[data-step]")];
  let scenario = scenarios[0], stage = 0, timer = null, playing = false, spoken = false, pending = null, requestVersion = 0;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const csrf = document.querySelector("#demoChatForm [name=csrfmiddlewaretoken]").value;

  function bubble(container, text, role, label) {
    const node = document.createElement("div");
    node.className = "chat-bubble " + role;
    if (label) { const caption = document.createElement("small"); caption.textContent = label; node.appendChild(caption); }
    node.appendChild(document.createTextNode(text)); container.appendChild(node); container.scrollTop = container.scrollHeight;
  }
  function stopVoice() { if ("speechSynthesis" in window) window.speechSynthesis.cancel(); }
  function speak(text) {
    if (!spoken || !("speechSynthesis" in window)) return;
    stopVoice(); const utterance = new SpeechSynthesisUtterance(text); utterance.rate = 1; window.speechSynthesis.speak(utterance);
  }
  function setPlaying(value) {
    clearTimeout(timer); playing = value; app.classList.toggle("is-playing", value);
    $("playWorkflow").textContent = value ? "Ⅱ Pause scenario" : stage === 3 ? "↻ Replay scenario" : "▶ Play scenario";
    if (!value) stopVoice();
  }
  function showStage(index, announce = false) {
    stage = index; const item = scenario.steps[stage];
    steps.forEach((button, i) => button.setAttribute("aria-pressed", String(i === stage)));
    $("sampleMessages").replaceChildren();
    bubble($("sampleMessages"), item.customer, "visitor", "Customer");
    bubble($("sampleMessages"), item.reply, "assistant", scenario.role);
    $("workflowStatus").textContent = stage === 3 ? "Sample handoff complete." : playing ? "Exploring the workflow…" : "Select a stage or press play.";
    $("stepCount").textContent = `0${stage + 1} / 04`;
    $("stepProgress").style.width = `${(stage + 1) * 25}%`;
    $("stepDetail").textContent = item.detail;
    $("leadName").textContent = stage >= 2 ? scenario.customer : "Waiting for details";
    $("leadInitials").textContent = stage >= 2 ? scenario.customer.split(" ").map(x => x[0]).join("") : "··";
    $("leadState").textContent = ["READY", "IN PROGRESS", "CAPTURED", "FOR REVIEW"][stage];
    $("leadNeed").textContent = stage >= 1 ? scenario.need : "—";
    $("leadPriority").textContent = stage >= 1 ? scenario.priority : "—";
    $("leadNext").textContent = stage === 3 ? scenario.next : stage === 2 ? "Prepare the handoff" : "Listen & understand";
    if (announce) speak(item.reply);
  }
  function scheduleNext() {
    timer = setTimeout(() => {
      if (!playing) return;
      if (stage === 3) { setPlaying(false); return; }
      showStage(stage + 1, true); scheduleNext();
    }, spoken ? 14500 : 6000);
  }
  function resetConversation() {
    requestVersion += 1; if (pending) pending.abort(); pending = null;
    $("demoSend").disabled = false; $("demoMessage").disabled = false;
    $("tryMessages").replaceChildren(); bubble($("tryMessages"), scenario.greeting, "assistant");
    for (const turn of chatHistory[scenario.id] || []) bubble($("tryMessages"), turn.content, turn.role === "user" ? "visitor" : "assistant");
    $("demoChatError").hidden = true; $("demoMessage").value = "";
    $("replyMode").textContent = "TRY A CONVERSATION";
    $("modeNote").textContent = "AI replies when available; guided sample replies otherwise. Use fictional details.";
  }
  function selectScenario(id) {
    scenario = scenarios.find(s => s.id === id) || scenarios[0]; setPlaying(false); stage = 0;
    tabs.forEach(button => { const selected = button.dataset.scenario === scenario.id; button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1; });
    $("scenario-panel").setAttribute("aria-labelledby", "tab-" + scenario.id);
    for (const [id, value] of Object.entries({scenarioRole:scenario.role, scenarioHeadline:scenario.headline, scenarioDescription:scenario.description, businessInitials:scenario.initials, businessName:scenario.business, businessRole:scenario.role + " · Sample conversation", tryBusiness:scenario.business})) $(id).textContent = value;
    $("scenarioSignup").href = scenario.signup_url;
    $("suggestedPrompts").replaceChildren();
    for (const prompt of scenario.prompts) { const button = document.createElement("button"); button.type = "button"; button.textContent = prompt; button.addEventListener("click", () => { if (pending) return; $("demoMessage").value = prompt; $("demoChatForm").requestSubmit(); }); $("suggestedPrompts").appendChild(button); }
    showStage(0); resetConversation(); $("playWorkflow").textContent = "▶ Play scenario";
  }
  tabs.forEach((button, index) => {
    button.addEventListener("click", () => selectScenario(button.dataset.scenario));
    button.addEventListener("keydown", event => {
      let next; if (event.key === "ArrowRight") next = (index + 1) % tabs.length; else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length; else if (event.key === "Home") next = 0; else if (event.key === "End") next = tabs.length - 1; else return;
      event.preventDefault(); tabs[next].focus(); selectScenario(tabs[next].dataset.scenario);
    });
  });
  steps.forEach(button => button.addEventListener("click", () => { setPlaying(false); showStage(Number(button.dataset.step), true); $("playWorkflow").textContent = stage === 3 ? "↻ Replay scenario" : "▶ Play scenario"; }));
  $("playWorkflow").addEventListener("click", () => { if (playing) { setPlaying(false); return; } if (stage === 3) stage = 0; setPlaying(true); showStage(stage, true); scheduleNext(); });
  $("resetDemo").addEventListener("click", () => { setPlaying(false); showStage(0); $("playWorkflow").textContent = "▶ Play scenario"; });
  if (!("speechSynthesis" in window)) { $("voiceToggle").disabled = true; $("voiceNote").textContent = "Spoken preview is unavailable in this browser."; }
  $("voiceToggle").addEventListener("click", () => { spoken = !spoken; $("voiceToggle").setAttribute("aria-pressed", String(spoken)); $("voiceToggle").setAttribute("aria-label", spoken ? "Disable spoken sample preview" : "Enable spoken sample preview"); $("voiceNote").textContent = spoken ? "Device voice on · sample conversation." : "Optional audio uses your device’s voice."; if (spoken) speak(scenario.steps[stage].reply); else stopVoice(); });
  $("clearChat").addEventListener("click", async () => {
    delete chatHistory[scenario.id];
    resetConversation(); const body = new FormData(); body.append("scenario", scenario.id); body.append("reset", "1");
    try { await fetch(app.dataset.chatUrl, {method:"POST", headers:{"X-CSRFToken":csrf}, body}); } catch (_) {}
    $("demoMessage").focus();
  });
  $("demoChatForm").addEventListener("submit", async event => {
    event.preventDefault(); const text = $("demoMessage").value.trim(); if (!text || pending) return;
    const version = ++requestVersion; pending = new AbortController(); const controller = pending;
    const body = new FormData(); body.append("scenario", scenario.id); body.append("message", text);
    $("demoSend").disabled = true; $("demoMessage").disabled = true; $("demoChatError").hidden = true; $("replyMode").textContent = "THINKING…";
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(app.dataset.chatUrl, {method:"POST", headers:{"X-CSRFToken":csrf}, body, signal:controller.signal});
      const data = await response.json(); if (version !== requestVersion) return;
      if (!response.ok) throw new Error(data.error || "The assistant is unavailable. Please try again.");
      bubble($("tryMessages"), text, "visitor"); bubble($("tryMessages"), data.reply, "assistant");
      chatHistory[scenario.id] = [...(chatHistory[scenario.id] || []), {role:"user",content:text}, {role:"assistant",content:data.reply}].slice(-12);
      $("demoMessage").value = ""; $("replyMode").textContent = data.mode === "ai" ? "AI DEMO" : "GUIDED PREVIEW";
      $("modeNote").textContent = data.mode === "ai" ? "AI-generated sample response. No real booking or message is sent." : "Guided sample response. AI is temporarily unavailable. No real action is taken.";
    } catch (error) {
      if (version !== requestVersion) return;
      $("demoChatError").textContent = error.name === "AbortError" ? "That took longer than expected. Please try again." : error.message;
      $("demoChatError").hidden = false; $("replyMode").textContent = "PLEASE TRY AGAIN";
    } finally {
      clearTimeout(timeout); if (version === requestVersion) { pending = null; $("demoSend").disabled = false; $("demoMessage").disabled = false; $("demoMessage").focus({preventScroll:true}); }
    }
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) { setPlaying(false); $("demoFilm").pause(); } });
  window.addEventListener("pagehide", () => { setPlaying(false); if (pending) pending.abort(); });
  // All playback starts with an explicit click, including in reduced-motion mode.
  reduced.addEventListener("change", () => setPlaying(false));
  selectScenario(scenario.id);
})();
