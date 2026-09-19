/**
 * MoneyTrace Frontend Engine
 * Implements:
 * 1. Full viewport width layout (edge-to-edge).
 * 2. Public landing page at / (no internal dashboard leak, CTA leads to /login).
 * 3. /login as the single authentication entry point with demo persona picker.
 * 4. Strict role-based navigation: USER -> /portal, FRAUD_OPERATOR -> /dashboard.
 * 5. Minimal squarish sidebar navigation (10-14px border radius).
 * 6. Preserves 100% of backend, SSE, Sarvam, Cognee, and n8n integrations.
 */

const MoneyTraceApp = (() => {
  let currentUser = null;
  let sseSource = null;
  let activeView = "landing";
  let activeIncidentId = "MT-10481";
  let activePipelineIncident = null;
  let pipelineEvents = [];
  let telemetryTimer = null;
  let shownSimilarityAlerts = new Set();

  // Audio / Mic State
  let mediaRecorder = null;
  let audioChunks = [];
  let isRecording = false;
  let selectedLanguage = "en";

  // Notifications
  let currentNotifications = [];

  const DEMO_USERS = {
    victim: { email: "victim@moneytrace.in", pass: "victim123" },
    victim2: { email: "victim2@moneytrace.in", pass: "victim123" },
    operator: { email: "operator@moneytrace.in", pass: "operator123" }
  };

  const STAGES = [
    { key: "INCIDENT_CREATED", title: "Report Received", service: "MoneyTrace Ingestion Gateway", desc: "Report registered in triage database." },
    { key: "INVESTIGATION_STARTED", title: "Investigation Started", service: "Investigation Agent", desc: "Narrative parsed & parameters extracted." },
    { key: "TRANSACTION_FOUND", title: "Transaction Identified", service: "Financial Ledger", desc: "Matched against transaction ledger & counterparty accounts." },
    { key: "SIGNALS_ANALYZED", title: "Signals Analyzed", service: "Risk Signal Classifier", desc: "Evaluated threat pattern, urgency, and destination risk." },
    { key: "RELATED_INCIDENTS_FOUND", title: "Syndicate Discovery (Cognee)", service: "Cognee Cloud API", desc: "Discovered related victim reports & shared scammer entities." },
    { key: "GRAPH_READY", title: "Scam Network Built", service: "Cognee Graph Engine", desc: "Interactive intelligence nodes assembled." },
    { key: "EVIDENCE_PREPARED", title: "Evidence Prepared", service: "Evidence Compiler", desc: "Forensic evidence package compiled and sealed." },
    { key: "N8N_WORKFLOW_STARTED", title: "n8n Response Dispatched", service: "n8n Orchestrator", desc: "Autonomous triage webhook workflow triggered." },
    { key: "N8N_WORKFLOW_COMPLETED", title: "n8n Response Completed", service: "n8n Webhook Engine", desc: "Response workflow executed successfully." },
    { key: "HUMAN_REVIEW_REQUIRED", title: "Human Review", service: "Fraud Ops Policy", desc: "High-risk escalation flagged for operator signoff." },
    { key: "INCIDENT_COMPLETED", title: "Completed", service: "Autonomous Pipeline", desc: "Incident triage concluded & audit trail recorded." },
    { key: "USER_NOTIFICATION_CREATED", title: "Victim Guidance Dispatched", service: "Victim Comms", desc: "User-safe protective advisory delivered to portal." }
  ];

  async function init() {
    const token = localStorage.getItem("mt_token");
    if (token) {
      try {
        const res = await fetch("/api/auth/me", {
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (res.ok) {
          currentUser = await res.json();
        } else {
          localStorage.removeItem("mt_token");
          currentUser = null;
        }
      } catch (e) {
        currentUser = null;
      }
    }

    setupSSE();
    window.addEventListener("popstate", routeFromUrl);
    routeFromUrl();
  }

  async function loginUser(email, pass) {
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password: pass })
      });
      if (res.ok) {
        const data = await res.json();
        localStorage.setItem("mt_token", data.access_token);
        currentUser = data.user;
        updateUserUI();
        showToast(`Authenticated as ${currentUser.name}`);
        
        // Redirect according to role
        if (currentUser.role === "FRAUD_OPERATOR") {
          navigate("/dashboard");
        } else {
          navigate("/portal");
        }
        return true;
      }
    } catch (e) {
      console.error("Login failed:", e);
    }
    showToast("Invalid credentials");
    return false;
  }

  function logout() {
    localStorage.removeItem("mt_token");
    currentUser = null;
    updateUserUI();
    showToast("Signed out");
    navigate("/");
  }

  function updateUserUI() {
    const nameEl = document.getElementById("userName");
    const roleEl = document.getElementById("userRole");
    const avatarEl = document.getElementById("userAvatar");
    const userPill = document.getElementById("userPill");
    const logoutBtn = document.getElementById("logoutBtn");
    const notifBellBtn = document.getElementById("notifBellBtn");

    if (currentUser) {
      if (nameEl) nameEl.innerText = currentUser.name.split(" ")[0];
      if (roleEl) roleEl.innerText = currentUser.role;
      if (avatarEl) avatarEl.innerText = currentUser.name.charAt(0);
      if (userPill) userPill.style.display = "flex";
      if (logoutBtn) logoutBtn.style.display = "flex";
      if (notifBellBtn) notifBellBtn.style.display = "flex";
    } else {
      if (userPill) userPill.style.display = "none";
      if (logoutBtn) logoutBtn.style.display = "none";
      if (notifBellBtn) notifBellBtn.style.display = "none";
    }

    renderNavRail();
  }

  function renderNavRail() {
    const rail = document.getElementById("appSidebarRail");
    if (!rail) return;

    const path = window.location.pathname;

    // Public pages (landing and login) have NO sidebar
    if (path === "/" || path === "/login" || !currentUser) {
      rail.classList.add("hidden");
      return;
    }

    rail.classList.remove("hidden");

    if (currentUser.role === "FRAUD_OPERATOR") {
      rail.innerHTML = `
        <button class="nav-item-rect ${path.startsWith('/dashboard') ? 'active' : ''}" onclick="MoneyTraceApp.navigate('/dashboard')" title="Fraud Operations Console">
          <svg viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
          <span>Console</span>
        </button>
        <button class="nav-item-rect ${path.startsWith('/investigations') ? 'active' : ''}" onclick="MoneyTraceApp.navigate('/investigations')" title="Live Pipeline">
          <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
          <span>Pipeline</span>
        </button>
        <button class="nav-item-rect ${path.startsWith('/cases') ? 'active' : ''}" onclick="MoneyTraceApp.navigate('/cases' + (activeIncidentId ? '/' + activeIncidentId : ''))" title="Case Workspace & Graph">
          <svg viewBox="0 0 24 24" fill="none"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
          <span>Cases</span>
        </button>
        <button class="nav-item-rect ${path.startsWith('/evaluation') ? 'active' : ''}" onclick="MoneyTraceApp.navigate('/evaluation')" title="Evaluation & Accuracy Benchmark">
          <svg viewBox="0 0 24 24" fill="none"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>
          <span>Accuracy</span>
        </button>
      `;
    } else {
      // USER Role (Victim)
      rail.innerHTML = `
        <button class="nav-item-rect ${path.startsWith('/portal') ? 'active' : ''}" onclick="MoneyTraceApp.navigate('/portal')" title="Report Fraud">
          <svg viewBox="0 0 24 24" fill="none"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          <span>Report</span>
        </button>
        <button class="nav-item-rect" onclick="MoneyTraceApp.toggleNotificationsPanel()" title="Protective Guidance">
          <svg viewBox="0 0 24 24" fill="none"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>
          <span>Alerts</span>
        </button>
      `;
    }
  }

  function setupSSE() {
    if (sseSource) sseSource.close();
    sseSource = new EventSource("/api/events");

    sseSource.onopen = () => {
      const text = document.getElementById("sseText");
      if (text) text.innerText = "Realtime Active";
    };

    sseSource.onerror = () => {
      const text = document.getElementById("sseText");
      if (text) text.innerText = "Reconnecting SSE...";
    };

    sseSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        handleIncomingEvent(event);
      } catch (err) {}
    };
  }

  function handleIncomingEvent(event) {
    if (!event || !event.event_type) return;

    if (activeView === "investigations") {
      if (!activePipelineIncident && event.incident_id) {
        activePipelineIncident = event.incident_id;
      }
      if (activePipelineIncident === event.incident_id) {
        pipelineEvents.push(event);
        updatePipelineEventUI(event, true);
      }
    }

    if (activeView === "dashboard") {
      if (["INCIDENT_CREATED", "INCIDENT_COMPLETED"].includes(event.event_type)) {
        fetchDashboardData();
      }
    }

    if (activeView === "portal") {
      if (["USER_NOTIFICATION_CREATED", "INCIDENT_COMPLETED"].includes(event.event_type)) {
        fetchPortalUserData();
      }
    }

    const badge = document.getElementById("notifCountBadge");
    if (badge) {
      badge.style.display = "flex";
      badge.innerText = parseInt(badge.innerText || "0") + 1;
    }

    showToast(`${event.event_type}: Incident ${event.incident_id}`);
  }

  function navigate(path) {
    window.history.pushState({}, "", path);
    routeFromUrl();
  }

  function routeFromUrl() {
    const path = window.location.pathname;
    const ctx = document.getElementById("viewContextTitle");

    // AUTH GUARD: If accessing internal routes anonymously, redirect to /login
    const protectedRoutes = ["/portal", "/investigations", "/cases", "/dashboard", "/evaluation"];
    const isProtected = protectedRoutes.some(r => path.startsWith(r));

    if (isProtected && !currentUser) {
      window.history.replaceState({}, "", "/login");
      activeView = "login";
      if (ctx) ctx.innerHTML = `<strong>Authentication Required</strong>`;
      updateUserUI();
      renderLoginView();
      return;
    }

    // ROLE GUARD: USER trying to access operator routes
    if (currentUser && currentUser.role === "USER" && (path.startsWith("/investigations") || path.startsWith("/cases") || path.startsWith("/dashboard") || path.startsWith("/evaluation"))) {
      window.history.replaceState({}, "", "/portal");
      activeView = "portal";
      showToast("Access restricted: operator authorization required.");
      updateUserUI();
      renderPortalView();
      return;
    }

    updateUserUI();

    if (path === "/") {
      activeView = "landing";
      if (ctx) ctx.innerHTML = `<span style="color:var(--text-muted);">Overview</span> / <strong>Autonomous Emergency Response</strong>`;
      renderLandingView();
    } else if (path === "/login") {
      activeView = "login";
      if (ctx) ctx.innerHTML = `<strong>Sign In</strong>`;
      renderLoginView();
    } else if (path.startsWith("/portal")) {
      activeView = "portal";
      if (ctx) ctx.innerHTML = `<span style="color:var(--text-muted);">Victim Portal</span> / <strong>Emergency Incident Intake</strong>`;
      renderPortalView();
    } else if (path.startsWith("/investigations")) {
      activeView = "investigations";
      if (ctx) ctx.innerHTML = `<span style="color:var(--text-muted);">Operations</span> / <strong>Live Investigation Pipeline</strong>`;
      renderInvestigationsView();
    } else if (path.startsWith("/cases")) {
      activeView = "cases";
      const parts = path.split("/");
      const incId = parts[2] || activeIncidentId || "MT-10481";
      activeIncidentId = incId;
      if (ctx) ctx.innerHTML = `<span style="color:var(--text-muted);">Case Intelligence</span> / <strong>Case ${incId}</strong>`;
      renderCasesView(incId);
    } else if (path.startsWith("/dashboard")) {
      activeView = "dashboard";
      if (ctx) ctx.innerHTML = `<span style="color:var(--text-muted);">Command Center</span> / <strong>Fraud Operations Console</strong>`;
      renderDashboardView();
    } else if (path.startsWith("/evaluation")) {
      activeView = "evaluation";
      if (ctx) ctx.innerHTML = `<span style="color:var(--text-muted);">Empirical Verification</span> / <strong>Evaluation & Accuracy Benchmark</strong>`;
      renderEvaluationView();
    }
  }

  // ==========================================
  // VIEW 1: PUBLIC LANDING PAGE (/)
  // ==========================================

  function renderLandingView() {
    const main = document.getElementById("mainApp");
    main.innerHTML = `
      <div class="landing-container">
        <!-- Hero Section -->
        <section class="landing-hero">
          <div class="landing-pill-badge">
            <span class="pulse-dot-green"></span>
            Paytm Build for India Hackathon — Autonomous AI Teammates
          </div>
          <h1 class="landing-title">
            Financial fraud doesn't wait.<br />
            <span>Neither should the response.</span>
          </h1>
          <p class="landing-subtitle">
            MoneyTrace turns a victim's first fraud report into an autonomous financial emergency response.
            From Indian-language voice statement to scam syndicate discovery, evidence preparation, and workflow escalation in seconds.
          </p>
          <div class="landing-cta-row">
            <button class="btn-cyan" onclick="MoneyTraceApp.navigate('/login')">
              Report a suspicious payment
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
            </button>
            <button class="btn-secondary-light" onclick="document.getElementById('howItWorksSec').scrollIntoView({behavior:'smooth'})">
              See how it works
            </button>
          </div>
        </section>

        <!-- How It Works Flow -->
        <section id="howItWorksSec" class="frosted-card">
          <div class="card-header-clean">
            <div>
              <div class="card-title-main">How MoneyTrace Works</div>
              <div class="card-subtitle">One report triggers an autonomous financial emergency response</div>
            </div>
            <span class="status-pill success">Autonomous Triage</span>
          </div>

          <div class="landing-flow-grid">
            <div class="landing-step-card">
              <div class="step-num-badge">1</div>
              <strong style="color:var(--brand-dark-navy); font-size:14px;">Report</strong>
              <div style="font-size:12.5px; color:var(--text-muted); line-height:1.5;">
                Victim reports suspected fraud via native voice statement (Sarvam AI) or text and screenshot.
              </div>
            </div>

            <div class="landing-step-card">
              <div class="step-num-badge">2</div>
              <strong style="color:var(--brand-dark-navy); font-size:14px;">Understand</strong>
              <div style="font-size:12.5px; color:var(--text-muted); line-height:1.5;">
                Investigation Agent extracts entities, checks transaction telemetry, and detects red flags.
              </div>
            </div>

            <div class="landing-step-card">
              <div class="step-num-badge">3</div>
              <strong style="color:var(--brand-dark-navy); font-size:14px;">Connect</strong>
              <div style="font-size:12.5px; color:var(--text-muted); line-height:1.5;">
                Cognee correlates shared UPI IDs, phone numbers, and domains to expose underlying scam syndicates.
              </div>
            </div>

            <div class="landing-step-card">
              <div class="step-num-badge">4</div>
              <strong style="color:var(--brand-dark-navy); font-size:14px;">Respond</strong>
              <div style="font-size:12.5px; color:var(--text-muted); line-height:1.5;">
                Forensic evidence is compiled, n8n executes response workflows, and victim receives safe guidance.
              </div>
            </div>
          </div>
        </section>

        <!-- Investigation Ecosystem Preview -->
        <section>
          <div style="text-align:center; margin-bottom:28px;">
            <h3 style="font-size:24px; font-weight:800; color:var(--brand-dark-navy);">The MoneyTrace Investigation Ecosystem</h3>
            <p style="font-size:14px; color:var(--text-muted); margin-top:4px;">Four synchronized operations views running on a single real-time event bus</p>
          </div>

          <div class="landing-ecosystem-grid">
            <div class="ecosystem-card">
              <div class="ecosystem-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
              </div>
              <strong style="font-size:14px; color:var(--brand-dark-navy);">Victim Intake Portal</strong>
              <p style="font-size:12.5px; color:var(--text-body); line-height:1.5;">Multilingual voice recording in Hindi, Tamil, Kannada, and English with payment receipt OCR.</p>
            </div>

            <div class="ecosystem-card">
              <div class="ecosystem-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              </div>
              <strong style="font-size:14px; color:var(--brand-dark-navy);">Live Pipeline</strong>
              <p style="font-size:12.5px; color:var(--text-body); line-height:1.5;">Autonomous execution track progressing in real-time across ledger verification, signals, and n8n response.</p>
            </div>

            <div class="ecosystem-card">
              <div class="ecosystem-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
              </div>
              <strong style="font-size:14px; color:var(--brand-dark-navy);">Scam Network Graph</strong>
              <p style="font-size:12.5px; color:var(--text-body); line-height:1.5;">Interactive relationship graph linking connected victim reports and shared counterparty entities.</p>
            </div>

            <div class="ecosystem-card">
              <div class="ecosystem-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
              </div>
              <strong style="font-size:14px; color:var(--brand-dark-navy);">Fraud Operations Console</strong>
              <p style="font-size:12.5px; color:var(--text-body); line-height:1.5;">Real-time queue management, syndicate exposure totals, and high-risk operator signoff triage.</p>
            </div>
          </div>
        </section>

        <!-- Trust & Boundary Statement -->
        <section style="background:var(--brand-dark-navy); color:#fff; border-radius:var(--radius-xl); padding:32px 40px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <h4 style="font-size:17px; font-weight:800; margin-bottom:6px;">Safety & Operations Boundary</h4>
            <p style="font-size:13px; color:#94A3B8; max-width:700px; line-height:1.5;">
              MoneyTrace operates on synthetic financial ledger data. It autonomously coordinates emergency triage and evidence assembly, but does not directly freeze or reverse banking funds without verified human operator review.
            </p>
          </div>
          <button class="btn-cyan" onclick="MoneyTraceApp.navigate('/login')">Sign In with Demo Role</button>
        </section>
      </div>
    `;
  }

  // ==========================================
  // VIEW 2: LOGIN VIEW (/login)
  // Single Entry Point for Demo Credentials
  // ==========================================

  function renderLoginView() {
    const main = document.getElementById("mainApp");
    main.innerHTML = `
      <div class="login-center-wrapper">
        <div class="login-card">
          <div style="text-align:center; margin-bottom:28px;">
            <img src="/public/moneytrace_logo.png" alt="MoneyTrace" style="height:44px; margin:0 auto;" />
            <h2 style="font-size:22px; font-weight:800; color:var(--brand-dark-navy); margin-top:14px;">Sign in to MoneyTrace</h2>
            <p style="font-size:13px; color:var(--text-muted); margin-top:4px;">Autonomous Financial Emergency Response Platform</p>
          </div>

          <form onsubmit="event.preventDefault(); MoneyTraceApp.handleFormLogin();" style="display:flex; flex-direction:column; gap:16px;">
            <div>
              <label style="font-size:12px; font-weight:700; color:var(--brand-dark-navy); margin-bottom:6px; display:block;">Email Address</label>
              <input type="email" id="loginEmail" class="input-clean" value="victim@moneytrace.in" required />
            </div>
            <div>
              <label style="font-size:12px; font-weight:700; color:var(--brand-dark-navy); margin-bottom:6px; display:block;">Password</label>
              <input type="password" id="loginPass" class="input-clean" value="victim123" required />
            </div>
            <button type="submit" class="btn-primary-dark" style="margin-top:6px; width:100%;">Sign In</button>
          </form>

          <!-- Explicit Demo Persona Selector -->
          <div class="demo-role-box">
            <div style="font-size:11.5px; font-weight:800; text-transform:uppercase; color:var(--text-muted); margin-bottom:12px;">Demo Access (Judges & Evaluators)</div>
            
            <div class="demo-persona-card" onclick="MoneyTraceApp.quickSelectDemo('victim@moneytrace.in', 'victim123')">
              <div>
                <strong style="color:var(--brand-dark-navy); font-size:13px;">Victim User</strong>
                <div style="font-size:11.5px; color:var(--text-muted);">victim@moneytrace.in (Isolated reporting portal)</div>
              </div>
              <span class="status-pill info">USER</span>
            </div>

            <div class="demo-persona-card" onclick="MoneyTraceApp.quickSelectDemo('operator@moneytrace.in', 'operator123')">
              <div>
                <strong style="color:var(--brand-dark-navy); font-size:13px;">Fraud Operator</strong>
                <div style="font-size:11.5px; color:var(--text-muted);">operator@moneytrace.in (Live pipeline, cases & console)</div>
              </div>
              <span class="status-pill critical">OPERATOR</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function quickSelectDemo(email, pass) {
    document.getElementById("loginEmail").value = email;
    document.getElementById("loginPass").value = pass;
    loginUser(email, pass);
  }

  async function handleFormLogin() {
    const email = document.getElementById("loginEmail").value.trim();
    const pass = document.getElementById("loginPass").value.trim();
    loginUser(email, pass);
  }

  function handleProfileClick() {
    // Show current user info modal or signout option
    if (currentUser) {
      showToast(`Signed in as ${currentUser.name} (${currentUser.role})`);
    }
  }

  // ==========================================
  // VIEW 3: USER PORTAL (/portal)
  // ==========================================

  function renderPortalView() {
    const main = document.getElementById("mainApp");
    main.innerHTML = `
      <div class="portal-grid">
        <!-- Left: Incident Intake Flow -->
        <div>
          <!-- Voice Intake Card -->
          <div class="voice-navy-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px;">
              <div>
                <span style="font-size:11px; font-weight:800; letter-spacing:0.5px; color:#38BDF8; text-transform:uppercase;">Multilingual Voice Statement</span>
                <h3 style="font-size:18px; font-weight:800; margin-top:2px;">Speak Your Report</h3>
              </div>
              <div style="display:flex; gap:6px;">
                <button class="btn-secondary-light ${selectedLanguage === 'en' ? 'btn-cyan' : ''}" style="padding:4px 10px; font-size:11.5px;" onclick="MoneyTraceApp.setLanguage('en')">EN</button>
                <button class="btn-secondary-light ${selectedLanguage === 'hi' ? 'btn-cyan' : ''}" style="padding:4px 10px; font-size:11.5px;" onclick="MoneyTraceApp.setLanguage('hi')">हिन्दी</button>
                <button class="btn-secondary-light ${selectedLanguage === 'ta' ? 'btn-cyan' : ''}" style="padding:4px 10px; font-size:11.5px;" onclick="MoneyTraceApp.setLanguage('ta')">தமிழ்</button>
                <button class="btn-secondary-light ${selectedLanguage === 'kn' ? 'btn-cyan' : ''}" style="padding:4px 10px; font-size:11.5px;" onclick="MoneyTraceApp.setLanguage('kn')">ಕನ್ನಡ</button>
              </div>
            </div>

            <div style="display:flex; align-items:center; gap:16px;">
              <button class="mic-action-btn ${isRecording ? 'recording' : ''}" id="portalMicBtn" onclick="MoneyTraceApp.toggleVoiceRecord()">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>
              </button>
              <div>
                <div style="font-size:14px; font-weight:700;" id="voiceStatusTitle">${isRecording ? 'Recording audio statement...' : 'Tap to start voice statement'}</div>
                <div style="font-size:12px; color:#94A3B8;" id="voiceProviderLabel">Supported by Sarvam Cloud Speech AI</div>
              </div>
            </div>
          </div>

          <!-- Form Details -->
          <div class="frosted-card">
            <div class="card-header-clean">
              <div>
                <h3 class="card-title-main">Report Suspicious Payment</h3>
                <p class="card-subtitle">Autonomous financial emergency triage for ${currentUser ? currentUser.name : 'Victim'}.</p>
              </div>
              <a onclick="MoneyTraceApp.fillSampleScenario()" style="font-size:12px; color:var(--brand-cyan-hover); font-weight:700; cursor:pointer; text-decoration:underline;">
                Prefill realistic KYC case
              </a>
            </div>

            <form onsubmit="event.preventDefault(); MoneyTraceApp.submitReport();" style="display:flex; flex-direction:column; gap:16px;">
              <div>
                <label style="font-size:12px; font-weight:700; color:var(--brand-dark-navy); margin-bottom:6px; display:block;">Incident Narrative / Statement</label>
                <textarea id="narrativeInput" class="input-clean" style="min-height:95px; resize:vertical;" placeholder="Describe what happened in detail..."></textarea>
              </div>

              <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
                <div>
                  <label style="font-size:12px; font-weight:700; color:var(--brand-dark-navy); margin-bottom:6px; display:block;">Transaction ID (Optional)</label>
                  <input type="text" id="txIdInput" class="input-clean" placeholder="e.g. TXN784219" />
                </div>
                <div>
                  <label style="font-size:12px; font-weight:700; color:var(--brand-dark-navy); margin-bottom:6px; display:block;">Amount (₹ INR)</label>
                  <input type="number" id="amountInput" class="input-clean" placeholder="e.g. 18500" />
                </div>
              </div>

              <div>
                <label style="font-size:12px; font-weight:700; color:var(--brand-dark-navy); margin-bottom:6px; display:block;">Payment Screenshot (Optional with OCR)</label>
                <input type="file" id="screenshotInput" class="input-clean" accept="image/*" onchange="MoneyTraceApp.handleScreenshotUpload(event)" />
                <div id="screenshotPreviewBox" style="display:none; margin-top:10px;"></div>
              </div>

              <button type="submit" class="btn-primary-dark" style="margin-top:8px;">
                Submit Emergency Report
              </button>
            </form>
          </div>
        </div>

        <!-- Right: Status & Protective Guidance -->
        <div style="display:flex; flex-direction:column; gap:20px;">
          <div class="frosted-card" id="portalStatusCard">
            <div class="card-header-clean">
              <div>
                <h4 class="card-title-main" style="font-size:15px;">Your Protection Status</h4>
                <p class="card-subtitle">Active emergency case</p>
              </div>
              <span class="status-pill info">Monitoring</span>
            </div>
            <div id="portalStatusContent">
              <div style="font-size:13px; color:var(--text-body); line-height:1.5;">
                No emergency investigations currently running for this user. Submit a report on the left to begin autonomous response.
              </div>
            </div>
          </div>

          <div class="frosted-card">
            <div class="card-header-clean">
              <div>
                <h4 class="card-title-main" style="font-size:15px;">Protective Guidance</h4>
                <p class="card-subtitle">Safe action recommendations</p>
              </div>
            </div>
            <div id="portalNotificationsList" style="display:flex; flex-direction:column; gap:10px;">
              <div style="font-size:12.5px; color:var(--text-muted); padding:8px 0;">Loading protective advisories...</div>
            </div>
          </div>
        </div>
      </div>
    `;

    fetchPortalUserData();
  }

  async function fetchPortalUserData() {
    const token = localStorage.getItem("mt_token");
    if (!token) return;

    try {
      const repRes = await fetch("/api/portal/my-reports", {
        headers: { "Authorization": `Bearer ${token}` }
      });
      const repData = await repRes.json();
      const statusContent = document.getElementById("portalStatusContent");

      if (statusContent && repData.reports && repData.reports.length > 0) {
        const latest = repData.reports[0];
        const isProgress = latest.investigation_stage !== "COMPLETE";

        statusContent.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <strong>Ref: ${latest.id}</strong>
            <span class="status-pill ${isProgress ? 'warning' : 'success'}">${latest.status}</span>
          </div>
          <div style="font-size:12.5px; color:var(--text-body); line-height:1.5;">
            ${isProgress ? 'Report submitted — investigation in progress. You will receive safe guidance once our autonomous pipeline completes.' : 'Investigation complete. Review recommended protective actions below.'}
          </div>
        `;
      }

      const notifRes = await fetch("/api/portal/notifications", {
        headers: { "Authorization": `Bearer ${token}` }
      });
      const notifData = await notifRes.json();
      currentNotifications = notifData.notifications || [];
      const listEl = document.getElementById("portalNotificationsList");

      if (listEl) {
        if (currentNotifications.length === 0) {
          listEl.innerHTML = `<div style="font-size:12.5px; color:var(--text-muted);">No advisories yet. Notifications will appear when investigation completes.</div>`;
        } else {
          listEl.innerHTML = currentNotifications.map(n => `
            <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:12px; cursor:pointer;" onclick="MoneyTraceApp.showNotificationModal('${n.id}')">
              <div style="font-weight:700; color:var(--brand-dark-navy); font-size:13px;">${n.title}</div>
              <div style="font-size:12px; color:var(--text-body); margin-top:2px;">${n.summary}</div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">${n.created_at} • Click to read</div>
            </div>
          `).join("");
        }
      }
    } catch (e) {
      console.warn("Portal fetch error:", e);
    }
  }

  async function toggleVoiceRecord() {
    const btn = document.getElementById("portalMicBtn");
    const statusTitle = document.getElementById("voiceStatusTitle");
    const providerLabel = document.getElementById("voiceProviderLabel");

    if (!isRecording) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
          const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
          stream.getTracks().forEach(track => track.stop());

          if (statusTitle) statusTitle.innerText = "Transcribing with Sarvam AI...";
          const formData = new FormData();
          formData.append("audio", audioBlob, "statement.wav");
          formData.append("language", selectedLanguage);

          try {
            const res = await fetch("/api/voice/transcribe", { method: "POST", body: formData });
            const data = await res.json();
            const narrativeInput = document.getElementById("narrativeInput");
            if (narrativeInput && data.transcript) {
              narrativeInput.value = data.transcript;
            }
            if (statusTitle) statusTitle.innerText = "Statement transcribed";
            if (providerLabel) providerLabel.innerText = data.provider || "Sarvam Cloud AI";
            showToast(`Voice processed via ${data.provider}`);
          } catch (err) {
            console.error("Sarvam transcription error:", err);
            if (statusTitle) statusTitle.innerText = "Transcription failed";
          }
        };

        mediaRecorder.start();
        isRecording = true;
        if (btn) btn.classList.add("recording");
        if (statusTitle) statusTitle.innerText = "Recording... Speak clearly";
      } catch (err) {
        console.error("Mic access denied:", err);
        showToast("Microphone permission required.");
      }
    } else {
      if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
      isRecording = false;
      if (btn) btn.classList.remove("recording");
    }
  }

  async function handleScreenshotUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    const token = localStorage.getItem("mt_token");
    const previewBox = document.getElementById("screenshotPreviewBox");

    const formData = new FormData();
    formData.append("file", file);

    try {
      showToast("Extracting OCR details from screenshot...");
      const res = await fetch("/api/portal/upload-screenshot", {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` },
        body: formData
      });
      const data = await res.json();

      if (previewBox) {
        previewBox.style.display = "block";
        previewBox.innerHTML = `
          <div style="display:flex; gap:12px; align-items:center; background:#EFF6FF; padding:10px 14px; border-radius:var(--radius-sm); border:1px solid #BFDBFE;">
            <img src="${data.screenshot_url}" style="height:60px; border-radius:6px; object-fit:contain;" />
            <div style="font-size:12px; color:#1E40AF;">
              <strong>${data.ocr_data.detected_type}</strong> (Confidence: ${Math.round(data.ocr_data.confidence * 100)}%)
              <div>Txn: ${data.ocr_data.extracted_fields.transaction_id} • ₹${data.ocr_data.extracted_fields.amount}</div>
            </div>
          </div>
        `;
      }

      const txInput = document.getElementById("txIdInput");
      const amtInput = document.getElementById("amountInput");
      if (txInput && !txInput.value) txInput.value = data.ocr_data.extracted_fields.transaction_id;
      if (amtInput && !amtInput.value) amtInput.value = data.ocr_data.extracted_fields.amount;

      window._currentScreenshot = data.screenshot_url;
      window._currentOcr = data.ocr_data;
    } catch (e) {
      console.error("Screenshot upload failed:", e);
    }
  }

  function fillSampleScenario() {
    document.getElementById("narrativeInput").value = "Someone called saying my KYC would expire. They asked me to transfer money to update it. I transferred ₹18,500 to kyc-update.pay@ybl and now I think it was a scam.";
    document.getElementById("txIdInput").value = "TXN784219";
    document.getElementById("amountInput").value = "18500";
  }

  async function submitReport() {
    const token = localStorage.getItem("mt_token");
    const narrative = document.getElementById("narrativeInput").value.trim();
    const txId = document.getElementById("txIdInput").value.trim();
    const amount = parseFloat(document.getElementById("amountInput").value) || null;

    if (!narrative) {
      showToast("Please provide a description or record your voice.");
      return;
    }

    const payload = {
      narrative,
      language: selectedLanguage,
      transaction_id: txId || null,
      amount,
      screenshot_url: window._currentScreenshot || null,
      ocr_data: window._currentOcr || null
    };

    try {
      const res = await fetch("/api/portal/reports", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const data = await res.json();
        activePipelineIncident = data.incident_id;
        activeIncidentId = data.incident_id;

        const statusContent = document.getElementById("portalStatusContent");
        if (statusContent) {
          statusContent.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <strong>Ref: ${data.incident_id}</strong>
              <span class="status-pill warning">INVESTIGATING</span>
            </div>
            <div style="font-size:12.5px; color:var(--text-body);">
              Report submitted — investigation in progress. You will receive safe guidance once our autonomous pipeline completes.
            </div>
          `;
        }

        showToast(`Report submitted! Case ${data.incident_id} under investigation.`);
        document.getElementById("narrativeInput").value = "";
      }
    } catch (e) {
      console.error("Submit report error:", e);
    }
  }

  function setLanguage(lang) {
    selectedLanguage = lang;
    renderPortalView();
  }

  // ==========================================
  // VIEW 4: LIVE INVESTIGATIONS (/investigations)
  // ==========================================

  async function renderInvestigationsView() {
    const main = document.getElementById("mainApp");
    const token = localStorage.getItem("mt_token");

    let incidentList = [];
    try {
      const res = await fetch("/api/incidents", {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        incidentList = data.incidents || [];
      }
    } catch (e) {
      console.warn("Could not load incidents list:", e);
    }

    const currentId = activePipelineIncident || (incidentList.length > 0 ? incidentList[0].id : "MT-10481");
    activePipelineIncident = currentId;

    main.innerHTML = `
      <div class="investigations-layout-3">
        <!-- Left: Incident Queue -->
        <div class="frosted-card" style="padding:20px;">
          <div class="card-header-clean">
            <div>
              <h4 class="card-title-main" style="font-size:14px;">Incident Queue</h4>
              <p class="card-subtitle">Active response triage</p>
            </div>
          </div>
          <div style="display:flex; flex-direction:column; gap:10px; max-height:640px; overflow-y:auto;">
            ${incidentList.map(i => `
              <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:12px; cursor:pointer; border:1px solid ${i.id === currentId ? 'var(--brand-cyan)' : 'transparent'};" onclick="MoneyTraceApp.selectPipelineIncident('${i.id}')">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <strong style="color:var(--brand-dark-navy); font-size:13px;">${i.id}</strong>
                  <span class="status-pill ${i.severity === 'CRITICAL' ? 'critical' : 'warning'}">${i.severity}</span>
                </div>
                <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
                  ₹${(i.amount || 0).toLocaleString()} • ${i.scam_type || 'Triage'}
                </div>
              </div>
            `).join("")}
          </div>
        </div>

        <!-- Center: Investigation Pipeline Flow -->
        <div class="frosted-card">
          <div class="card-header-clean">
            <div>
              <h3 class="card-title-main">Live Investigation: ${currentId}</h3>
              <p class="card-subtitle">Realtime autonomous multi-agent execution track</p>
            </div>
            <button class="btn-primary-dark" style="padding:8px 18px; font-size:12.5px;" onclick="MoneyTraceApp.rerunInvestigation('${currentId}')">
              Rerun Pipeline
            </button>
          </div>

          <div id="pipelineOutcomeHighlight"></div>

          <div style="display:flex; flex-direction:column; gap:14px;" id="pipelineCentralTrack">
            ${STAGES.map((s, idx) => `
              <div class="pipeline-node-row" id="node_${s.key}">
                <div class="node-number">${idx + 1}</div>
                <div class="node-box">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:13.5px;">${s.title}</strong>
                    <span style="font-size:11px; background:var(--bg-subtle); padding:2px 8px; border-radius:var(--radius-full); font-weight:700; color:var(--text-muted);">${s.service}</span>
                  </div>
                  <div style="font-size:12px; color:var(--text-body); margin-top:4px;" id="node_desc_${s.key}">
                    ${s.desc}
                  </div>
                  <!-- Live Progress Indicator -->
                  <div class="stage-progress-wrap" id="stage_progress_wrap_${s.key}">
                    <div class="stage-progress-track">
                      <div class="stage-progress-fill not-started" id="progress_fill_${s.key}"></div>
                    </div>
                    <span class="stage-progress-pct not-started" id="progress_pct_${s.key}">0%</span>
                  </div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>

        <!-- Right: Real-time Telemetry -->
        <div class="frosted-card" style="padding:20px;">
          <div class="card-header-clean">
            <div>
              <h4 class="card-title-main" style="font-size:14px;">Event Telemetry</h4>
              <p class="card-subtitle">Persistent SSE event log</p>
            </div>
          </div>
          <div id="telemetryLog" style="display:flex; flex-direction:column; gap:8px; font-size:12px; max-height:560px; overflow-y:auto;">
            <div id="telemetryEmptyPlaceholder" style="color:var(--text-muted);">Awaiting live event triggers...</div>
          </div>
        </div>
      </div>
    `;

    loadIncidentEventHistory(currentId);
  }

  async function loadIncidentEventHistory(incidentId) {
    const token = localStorage.getItem("mt_token");
    try {
      const res = await fetch(`/api/incidents/${incidentId}/events`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        const events = data.events || [];
        events.forEach(ev => {
          if (!ev.incident_id) ev.incident_id = incidentId;
          updatePipelineEventUI(ev, false);
        });
      }
    } catch (e) {
      console.warn("Event history load failed:", e);
    }
  }

  function updatePipelineEventUI(event, isLive = false) {
    const nodeEl = document.getElementById(`node_${event.event_type}`);
    const descEl = document.getElementById(`node_desc_${event.event_type}`);
    const fillEl = document.getElementById(`progress_fill_${event.event_type}`);
    const pctEl = document.getElementById(`progress_pct_${event.event_type}`);
    const logEl = document.getElementById("telemetryLog");
    const emptyEl = document.getElementById("telemetryEmptyPlaceholder");

    // 1. Mark this stage as completed (100%)
    if (nodeEl) {
      nodeEl.classList.remove("active", "failed");
      nodeEl.classList.add("completed");
    }
    if (fillEl && pctEl) {
      fillEl.className = "stage-progress-fill completed";
      pctEl.className = "stage-progress-pct completed";
      pctEl.textContent = "100%";
    }

    // 2. Format detailed message
    if (descEl && event.payload) {
      let text = event.payload.message || `Milestone reached: ${event.status}`;
      if (event.event_type === "TRANSACTION_FOUND") {
        text = `Matched Txn: ${event.payload.transaction_id} (₹${event.payload.amount}) Recipient: ${event.payload.recipient}`;
      } else if (event.event_type === "RELATED_INCIDENTS_FOUND") {
        text = `Identified ${event.payload.related_count} connected cases via ${event.service}. Exposure: ₹${(event.payload.total_exposure || 0).toLocaleString()}`;
      } else if (event.event_type === "N8N_WORKFLOW_COMPLETED") {
        text = `n8n response webhook executed successfully (${event.payload.stages_completed || 5} stages verified).`;
      }
      descEl.innerHTML = `<span style="color:var(--status-success); font-weight:700;">✓ ${text}</span>`;
    }

    // 3. Mark next stage as processing (active, ~70% shimmering) if not finished
    const currentIdx = STAGES.findIndex(s => s.key === event.event_type);
    if (currentIdx !== -1 && currentIdx < STAGES.length - 1 && event.event_type !== "INCIDENT_COMPLETED") {
      const nextStage = STAGES[currentIdx + 1];
      const nextNodeEl = document.getElementById(`node_${nextStage.key}`);
      const nextFillEl = document.getElementById(`progress_fill_${nextStage.key}`);
      const nextPctEl = document.getElementById(`progress_pct_${nextStage.key}`);

      if (nextNodeEl && !nextNodeEl.classList.contains("completed")) {
        nextNodeEl.classList.add("active");
        if (nextFillEl && nextPctEl) {
          nextFillEl.className = "stage-progress-fill processing";
          nextPctEl.className = "stage-progress-pct processing";
          nextPctEl.textContent = "70%";
        }
      }
    }

    // 4. Live Telemetry Insertion & Eye-Catching Highlight
    if (logEl) {
      if (emptyEl) emptyEl.remove();

      // Remove newest highlight from previous newest item
      const prevNewest = logEl.querySelector(".telemetry-item.newest");
      if (prevNewest) {
        prevNewest.classList.remove("newest");
        const badge = prevNewest.querySelector(".telemetry-new-badge");
        if (badge) badge.remove();
      }

      const row = document.createElement("div");
      row.className = "telemetry-item" + (isLive ? " newest" : "");

      const formattedTime = event.timestamp ? (event.timestamp.includes("T") ? event.timestamp.split("T")[1].slice(0, 8) : event.timestamp) : new Date().toLocaleTimeString();

      row.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
          <div style="display:flex; align-items:center; gap:6px;">
            ${isLive ? '<span class="telemetry-new-badge">✦ NEW</span>' : ''}
            <strong style="color:var(--brand-dark-navy); font-size:12.5px;">${event.event_type}</strong>
          </div>
          <span style="color:var(--text-muted); font-size:11px; font-family:monospace;">${formattedTime}</span>
        </div>
        <div style="font-size:11.5px; color:var(--text-body);">${event.service}</div>
        ${event.payload && event.payload.message ? `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${event.payload.message}</div>` : ''}
      `;

      logEl.prepend(row);

      // Transition newest highlight back to normal after 2.5 seconds if live
      if (isLive) {
        if (telemetryTimer) clearTimeout(telemetryTimer);
        telemetryTimer = setTimeout(() => {
          row.classList.remove("newest");
          const badge = row.querySelector(".telemetry-new-badge");
          if (badge) badge.remove();
        }, 2500);
      }
    }

    // 5. Similarity Found Popup / Alert (Real data from RELATED_INCIDENTS_FOUND / GRAPH_READY)
    if (["RELATED_INCIDENTS_FOUND", "GRAPH_READY"].includes(event.event_type) && event.payload) {
      const relCount = event.payload.related_count || (event.payload.nodes_count ? event.payload.nodes_count - 1 : 0);
      const incId = event.incident_id || activePipelineIncident;
      if (relCount > 0 && !shownSimilarityAlerts.has(incId)) {
        shownSimilarityAlerts.add(incId);
        const shared = (event.payload.shared_entities && event.payload.shared_entities.length > 0) 
          ? event.payload.shared_entities[0] 
          : null;
        const exposure = event.payload.total_exposure || 0;
        showSimilarityModal(incId, relCount, shared, exposure);
      }
    }

    // 6. Presentation of Final Outcome Highlight when investigation completed
    if (event.event_type === "INCIDENT_COMPLETED" && event.payload) {
      const outcomeContainer = document.getElementById("pipelineOutcomeHighlight");
      if (outcomeContainer) {
        const isApproved = event.payload.action === "APPROVED" || event.payload.final_status === "RESOLVED";
        const bannerIncId = event.incident_id || activePipelineIncident || activeIncidentId || "MT-10481";
        outcomeContainer.innerHTML = `
          <div class="investigation-outcome-banner ${isApproved ? 'approved' : ''}">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
              <div>
                <span class="status-pill ${isApproved ? 'success' : 'critical'}" style="font-size:10.5px;">
                  ${isApproved ? 'VERIFIED & RESOLVED' : 'HIGH RISK — FRAUDULENT PAYMENT'}
                </span>
                <h4 style="font-size:15px; font-weight:800; color:var(--brand-dark-navy); margin-top:6px;">
                  Investigation Complete: ${bannerIncId}
                </h4>
              </div>
              <button class="btn-secondary-light" style="padding:4px 12px; font-size:11.5px;" onclick="MoneyTraceApp.navigate('/cases/${bannerIncId}')">
                Open Case File →
              </button>
            </div>
            <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; font-size:12px; background:var(--bg-subtle); padding:10px 14px; border-radius:var(--radius-sm);">
              <div>
                <span style="color:var(--text-muted); font-size:11px;">Scam Classification:</span>
                <div style="font-weight:700; color:var(--brand-dark-navy);">${event.payload.scam_type || 'Fake KYC / UPI Impersonation'}</div>
              </div>
              <div>
                <span style="color:var(--text-muted); font-size:11px;">Severity Assessment:</span>
                <div style="font-weight:700; color:var(--status-critical);">${event.payload.severity || 'CRITICAL'}</div>
              </div>
              <div>
                <span style="color:var(--text-muted); font-size:11px;">Status:</span>
                <div style="font-weight:700; color:var(--brand-dark-navy);">${event.payload.final_status || event.payload.action || 'ESCALATED'}</div>
              </div>
            </div>
          </div>
        `;
      }
    }
  }

  function selectPipelineIncident(id) {
    if (telemetryTimer) clearTimeout(telemetryTimer);
    activePipelineIncident = id;
    renderInvestigationsView();
  }

  async function rerunInvestigation(id) {
    const token = localStorage.getItem("mt_token");
    if (telemetryTimer) clearTimeout(telemetryTimer);
    shownSimilarityAlerts.delete(id);
    showToast(`Rerunning investigation agent on ${id}...`);
    try {
      await fetch(`/api/incidents/${id}/investigate`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      showToast("Investigation pipeline re-executed!");
    } catch (e) {
      console.error("Rerun error:", e);
    }
  }

  // ==========================================
  // VIEW 5: CASE WORKSPACE (/cases/:id)
  // ==========================================

  async function renderCasesView(incidentId) {
    const main = document.getElementById("mainApp");
    const token = localStorage.getItem("mt_token");

    main.innerHTML = `<div style="text-align:center; padding:60px 0;">Loading Case Workspace for ${incidentId}...</div>`;

    try {
      const res = await fetch(`/api/incidents/${incidentId}`, {
        headers: { "Authorization": `Bearer ${token}` }
      });

      if (!res.ok) {
        if (res.status === 403) {
          main.innerHTML = `
            <div class="frosted-card" style="text-align:center; max-width:500px; margin:40px auto; padding:40px;">
              <h3 style="color:var(--status-critical); margin-bottom:10px;">Operator Privilege Required</h3>
              <p>Case Workspace contains confidential graph data and is restricted to <strong>FRAUD_OPERATOR</strong> role.</p>
              <button class="btn-primary-dark" style="margin-top:20px;" onclick="MoneyTraceApp.navigate('/login')">
                Sign In as Operator
              </button>
            </div>
          `;
          return;
        }
        if (res.status === 404) {
          main.innerHTML = `
            <div class="frosted-card" style="text-align:center; max-width:520px; margin:40px auto; padding:40px;">
              <div style="font-size:36px; margin-bottom:12px;">🔍</div>
              <h3 style="color:var(--brand-dark-navy); margin-bottom:8px;">Incident Not Found</h3>
              <p style="color:var(--text-muted); font-size:13px; line-height:1.5; margin-bottom:24px;">
                The requested case record <strong>${incidentId}</strong> does not exist in the active database or may have been purged.
              </p>
              <div style="display:flex; justify-content:center; gap:12px;">
                <button class="btn-primary-dark" onclick="MoneyTraceApp.navigate('/dashboard')">
                  Return to Console
                </button>
                <button class="btn-secondary-light" onclick="MoneyTraceApp.navigate('/investigations')">
                  View Live Pipeline
                </button>
              </div>
            </div>
          `;
          return;
        }
        main.innerHTML = `
          <div class="frosted-card" style="text-align:center; max-width:520px; margin:40px auto; padding:40px;">
            <h3 style="color:var(--status-critical); margin-bottom:10px;">Unable to Load Case</h3>
            <p style="color:var(--text-muted); font-size:13px;">Server returned status ${res.status}. Please check your connection or retry.</p>
            <button class="btn-secondary-light" style="margin-top:20px;" onclick="MoneyTraceApp.navigate('/dashboard')">
              Return to Console
            </button>
          </div>
        `;
        return;
      }

      const inc = await res.json();
      const pkg = inc.evidence_package || {};
      const related = pkg.related_incidents || [];
      const sharedEnts = pkg.shared_entities || [];

      main.innerHTML = `
        <div class="case-workspace-layout-3">
          <!-- Left: Case Summary -->
          <div class="frosted-card">
            <div class="card-header-clean">
              <div>
                <span class="status-pill ${inc.severity === 'CRITICAL' ? 'critical' : 'warning'}">${inc.severity}</span>
                <h3 class="card-title-main" style="margin-top:8px;">Case ${inc.id}</h3>
              </div>
              <button class="btn-secondary-light" style="padding:6px 14px; font-size:12px;" onclick="MoneyTraceApp.showEvidenceModal('${inc.id}')">
                Evidence JSON
              </button>
            </div>

            <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:16px; margin:16px 0; display:grid; grid-template-columns:1fr 1fr; gap:12px;">
              <div>
                <span style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Amount</span>
                <div style="font-size:17px; font-weight:800; color:var(--brand-dark-navy);">₹${(inc.amount || 0).toLocaleString()}</div>
              </div>
              <div>
                <span style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Scam Type</span>
                <div style="font-size:14px; font-weight:700; color:var(--brand-dark-navy);">${inc.scam_type}</div>
              </div>
            </div>

            <div>
              <label style="font-size:11.5px; font-weight:700; text-transform:uppercase; color:var(--text-muted);">Victim Statement</label>
              <div style="background:#fff; border:1px solid var(--border-subtle); border-radius:var(--radius-xs); padding:12px; font-size:13px; margin-top:6px; line-height:1.5;">
                "${inc.narrative || 'No statement provided.'}"
              </div>
            </div>

            <div style="margin-top:16px;">
              <label style="font-size:11.5px; font-weight:700; text-transform:uppercase; color:var(--text-muted);">Suspicious Signals Flagged</label>
              <ul style="padding-left:18px; margin-top:6px; font-size:12.5px; color:var(--status-critical); line-height:1.6;">
                ${(pkg.red_flags || ["Impersonation scam pattern", "Recipient VPA flagged in national registry"]).map(rf => `<li>${rf}</li>`).join("")}
              </ul>
            </div>

            <!-- Operator Action -->
            <div style="margin-top:24px; padding:16px; background:#FEF2F2; border:1px solid #FECACA; border-radius:var(--radius-sm);">
              <strong style="color:var(--status-critical); font-size:13px;">Operator Signoff Required</strong>
              <div style="font-size:12px; color:#7F1D1D; margin:4px 0 12px 0;">High-risk response workflow flagged for operator authorization.</div>
              <button class="btn-primary-dark" style="background:var(--status-critical); width:100%; border-color:var(--status-critical);" onclick="MoneyTraceApp.signoffIncident('${inc.id}')">
                Authorize & Confirm Escalation
              </button>
            </div>
          </div>

          <!-- Center: Interactive Cognee Graph -->
          <div class="frosted-card">
            <div class="card-header-clean">
              <div>
                <h3 class="card-title-main">Scam Network & Syndicate Intelligence</h3>
                <p class="card-subtitle">Relationship Layer: <strong>${pkg.intelligence_layer || 'Cognee Cloud API'}</strong></p>
              </div>
              <span class="status-pill warning">${related.length} Connected Cases</span>
            </div>

            <div class="canvas-network-box">
              <canvas id="syndicateCanvas" style="width:100%; height:100%;"></canvas>
            </div>

            <div style="margin-top:18px;">
              <label style="font-size:11.5px; font-weight:700; text-transform:uppercase; color:var(--text-muted); display:block; margin-bottom:8px;">
                Shared Counterparties Identified
              </label>
              <div style="display:flex; flex-wrap:wrap; gap:8px;">
                ${sharedEnts.map(e => `
                  <span style="background:var(--bg-subtle); border:1px solid var(--border-subtle); padding:5px 12px; border-radius:var(--radius-full); font-size:12px; font-weight:700; color:var(--brand-dark-navy);">
                    ${e}
                  </span>
                `).join("")}
              </div>
            </div>
          </div>

          <!-- Right: Connected Victims -->
          <div class="frosted-card">
            <div class="card-header-clean">
              <div>
                <h4 class="card-title-main" style="font-size:15px;">Connected Incidents</h4>
                <p class="card-subtitle">Shared scam network victims</p>
              </div>
            </div>

            <div style="display:flex; flex-direction:column; gap:10px; max-height:560px; overflow-y:auto;">
              ${related.map(r => `
                <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:12px; border:1px solid var(--border-subtle);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:13px;">${r.id}</strong>
                    <span style="font-weight:700; color:var(--brand-dark-navy);">₹${(r.amount || 0).toLocaleString()}</span>
                  </div>
                  <div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">
                    ${(r.match_reasons || []).join(" • ")}
                  </div>
                  <a onclick="MoneyTraceApp.navigate('/cases/${r.id}')" style="display:inline-block; margin-top:6px; font-size:12px; color:var(--brand-cyan-hover); font-weight:700; cursor:pointer;">
                    Open Case File →
                  </a>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      `;

      renderSyndicateCanvasGraph(inc, related, sharedEnts);
    } catch (e) {
      console.error("Cases view error:", e);
    }
  }

  function renderSyndicateCanvasGraph(inc, related, sharedEntities) {
    const canvas = document.getElementById("syndicateCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 440;

    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const entCoords = [];
    const entCount = Math.min(sharedEntities.length, 4);
    for (let i = 0; i < entCount; i++) {
      const angle = (i / entCount) * 2 * Math.PI;
      const x = centerX + Math.cos(angle) * 95;
      const y = centerY + Math.sin(angle) * 85;
      entCoords.push({ x, y, label: sharedEntities[i] });
    }

    const relCoords = [];
    const relCount = Math.min(related.length, 6);
    for (let i = 0; i < relCount; i++) {
      const angle = (i / relCount) * 2 * Math.PI + 0.35;
      const x = centerX + Math.cos(angle) * 175;
      const y = centerY + Math.sin(angle) * 155;
      relCoords.push({ x, y, id: related[i].id, amt: related[i].amount });
    }

    ctx.strokeStyle = "rgba(0, 186, 242, 0.45)";
    ctx.lineWidth = 2;
    entCoords.forEach(ec => {
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(ec.x, ec.y);
      ctx.stroke();
    });

    ctx.strokeStyle = "rgba(220, 38, 38, 0.4)";
    relCoords.forEach(rc => {
      if (entCoords.length > 0) {
        const target = entCoords[Math.floor(Math.random() * entCoords.length)];
        ctx.beginPath();
        ctx.moveTo(target.x, target.y);
        ctx.lineTo(rc.x, rc.y);
        ctx.stroke();
      }
    });

    entCoords.forEach(ec => {
      ctx.fillStyle = "#233554";
      ctx.beginPath();
      ctx.arc(ec.x, ec.y, 14, 0, 2 * Math.PI);
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.stroke();

      ctx.fillStyle = "#94A3B8";
      ctx.font = "10px 'Plus Jakarta Sans'";
      ctx.textAlign = "center";
      ctx.fillText(ec.label.substring(0, 14), ec.x, ec.y + 24);
    });

    relCoords.forEach(rc => {
      ctx.fillStyle = "#DC2626";
      ctx.beginPath();
      ctx.arc(rc.x, rc.y, 16, 0, 2 * Math.PI);
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.stroke();

      ctx.fillStyle = "#fff";
      ctx.font = "bold 10px 'Plus Jakarta Sans'";
      ctx.textAlign = "center";
      ctx.fillText(rc.id, rc.x, rc.y + 3.5);
    });

    ctx.fillStyle = "#00BAF2";
    ctx.beginPath();
    ctx.arc(centerX, centerY, 24, 0, 2 * Math.PI);
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 3;
    ctx.stroke();

    ctx.fillStyle = "#fff";
    ctx.font = "bold 11.5px 'Plus Jakarta Sans'";
    ctx.textAlign = "center";
    ctx.fillText(inc.id, centerX, centerY + 4);
  }

  async function signoffIncident(id) {
    const token = localStorage.getItem("mt_token");
    try {
      const res = await fetch(`/api/incidents/${id}/review`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ action: "APPROVED", notes: "Authorized by Fraud Operator." })
      });
      if (res.ok) {
        showToast(`Operator signoff confirmed for case ${id}.`);
        renderCasesView(id);
      }
    } catch (e) {
      console.error("Signoff error:", e);
    }
  }

  // ==========================================
  // VIEW 6: FRAUD DASHBOARD (/dashboard)
  // ==========================================

  async function renderDashboardView() {
    const main = document.getElementById("mainApp");
    const token = localStorage.getItem("mt_token");

    main.innerHTML = `<div style="text-align:center; padding:60px 0;">Loading Fraud Operations Console...</div>`;

    try {
      const res = await fetch("/api/dashboard", {
        headers: { "Authorization": `Bearer ${token}` }
      });

      if (!res.ok) {
        if (res.status === 403) {
          main.innerHTML = `
            <div class="frosted-card" style="text-align:center; max-width:500px; margin:40px auto; padding:40px;">
              <h3 style="color:var(--status-critical); margin-bottom:10px;">Operator Privilege Required</h3>
              <p>Fraud Operations Console is restricted to <strong>FRAUD_OPERATOR</strong> role.</p>
              <button class="btn-primary-dark" style="margin-top:20px;" onclick="MoneyTraceApp.navigate('/login')">
                Sign In as Operator
              </button>
            </div>
          `;
          return;
        }
        return;
      }

      const data = await res.json();
      main.innerHTML = `
        <div>
          <!-- Top KPI Row (4 Cards) -->
          <div class="kpi-grid-4">
            <div class="kpi-card">
              <span class="kpi-label">Active Investigations</span>
              <span class="kpi-val" id="d_active">${data.metrics.active_incidents}</span>
            </div>
            <div class="kpi-card">
              <span class="kpi-label">High-Risk Cases</span>
              <span class="kpi-val" style="color:var(--status-critical);" id="d_critical">${data.metrics.critical_incidents}</span>
            </div>
            <div class="kpi-card">
              <span class="kpi-label">Scam Networks Exposure</span>
              <span class="kpi-val" id="d_exposure">₹${Math.round(data.metrics.reported_exposure).toLocaleString()}</span>
            </div>
            <div class="kpi-card">
              <span class="kpi-label">Human Review Queue</span>
              <span class="kpi-val" style="color:var(--status-warning);" id="d_reviews">${data.metrics.human_reviews_required}</span>
            </div>
          </div>

          <!-- Active Syndicates -->
          <div class="frosted-card" style="margin-bottom:24px;">
            <div class="card-header-clean">
              <div>
                <h3 class="card-title-main">Active Scam Syndicates (Discovered via Cognee)</h3>
                <p class="card-subtitle">Correlated fraud rings discovered across multiple victims</p>
              </div>
            </div>

            <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:16px;">
              ${data.clusters.map(c => `
                <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:16px; border-left:4px solid var(--brand-cyan);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:14px;">${c.name}</strong>
                    <span class="status-pill critical">${c.status}</span>
                  </div>
                  <div style="font-size:12.5px; color:var(--text-body); margin-top:8px;">
                    <div><strong>Exposure:</strong> ₹${c.reported_exposure.toLocaleString()} (${c.incident_count} reports)</div>
                    <div><strong>Key Counterparty:</strong> <code style="background:#fff; padding:2px 6px; border-radius:4px;">${c.lead_entity}</code></div>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>

          <!-- Fluid Data Table -->
          <div class="frosted-card">
            <div class="card-header-clean">
              <div>
                <h3 class="card-title-main">Real-Time Ingestion & Triage Queue</h3>
                <p class="card-subtitle">Synchronized live via SSE event bus</p>
              </div>
            </div>

            <div style="overflow-x:auto;">
              <table class="fintech-data-table">
                <thead>
                  <tr>
                    <th>Case Ref</th>
                    <th>Victim</th>
                    <th>Amount</th>
                    <th>Scam Category</th>
                    <th>Severity</th>
                    <th>Counterparty Details</th>
                    <th>Status</th>
                    <th>Received At</th>
                  </tr>
                </thead>
                <tbody id="dashboardTbody">
                  ${data.incidents.map(inc => `
                    <tr onclick="MoneyTraceApp.navigate('/cases/${inc.id}')">
                      <td><strong>${inc.id}</strong></td>
                      <td>${inc.victim_name || 'Anonymous'}</td>
                      <td>₹${(inc.amount || 0).toLocaleString()}</td>
                      <td>${inc.scam_type || 'Triage'}</td>
                      <td><span class="status-pill ${inc.severity === 'CRITICAL' ? 'critical' : 'warning'}">${inc.severity}</span></td>
                      <td><code style="background:var(--bg-subtle); padding:2px 6px; border-radius:4px;">${inc.recipient_upi || inc.scammer_phone || 'Analyst Review'}</code></td>
                      <td><span class="status-pill success">${inc.status}</span></td>
                      <td>${inc.created_at || 'Recent'}</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      `;
    } catch (e) {
      console.error("Dashboard render failed:", e);
    }
  }

  async function fetchDashboardData() {
    const token = localStorage.getItem("mt_token");
    try {
      const res = await fetch("/api/dashboard", {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        const dActive = document.getElementById("d_active");
        const dCritical = document.getElementById("d_critical");
        const dExposure = document.getElementById("d_exposure");
        const dReviews = document.getElementById("d_reviews");

        if (dActive) dActive.innerText = data.metrics.active_incidents;
        if (dCritical) dCritical.innerText = data.metrics.critical_incidents;
        if (dExposure) dExposure.innerText = `₹${Math.round(data.metrics.reported_exposure).toLocaleString()}`;
        if (dReviews) dReviews.innerText = data.metrics.human_reviews_required;

        const tbody = document.getElementById("dashboardTbody");
        if (tbody && data.incidents) {
          tbody.innerHTML = data.incidents.map(inc => `
            <tr onclick="MoneyTraceApp.navigate('/cases/${inc.id}')">
              <td><strong>${inc.id}</strong></td>
              <td>${inc.victim_name || 'Anonymous'}</td>
              <td>₹${(inc.amount || 0).toLocaleString()}</td>
              <td>${inc.scam_type || 'Triage'}</td>
              <td><span class="status-pill ${inc.severity === 'CRITICAL' ? 'critical' : 'warning'}">${inc.severity}</span></td>
              <td><code style="background:var(--bg-subtle); padding:2px 6px; border-radius:4px;">${inc.recipient_upi || inc.scammer_phone || 'Analyst Review'}</code></td>
              <td><span class="status-pill success">${inc.status}</span></td>
              <td>${inc.created_at || 'Recent'}</td>
            </tr>
          `).join("");
        }
      }
    } catch (e) {
      console.warn("Failed to refresh dashboard:", e);
    }
  }

  // ==========================================
  // NOTIFICATIONS & MODALS
  // ==========================================

  function toggleNotificationsPanel() {
    const el = document.getElementById("notificationsDrawer");
    const badge = document.getElementById("notifCountBadge");
    if (badge) badge.style.display = "none";

    if (el) {
      const isVisible = el.style.display !== "none";
      el.style.display = isVisible ? "none" : "flex";

      if (!isVisible) {
        const body = document.getElementById("notificationsPanelBody");
        const title = document.getElementById("notifPanelTitle");
        const subtitle = document.getElementById("notifPanelSubtitle");

        if (currentUser && currentUser.role === "FRAUD_OPERATOR") {
          title.innerText = "Internal Pipeline Telemetry";
          subtitle.innerText = "Realtime investigation events";
          body.innerHTML = pipelineEvents.length === 0
            ? `<div style="font-size:12.5px; color:var(--text-muted);">No recent events recorded.</div>`
            : pipelineEvents.map(ev => `
                <div style="background:var(--bg-subtle); border-radius:var(--radius-xs); padding:12px;">
                  <strong style="color:var(--brand-dark-navy);">${ev.event_type}</strong>
                  <div style="font-size:12px; color:var(--text-body); margin-top:2px;">Incident: ${ev.incident_id} • Service: ${ev.service}</div>
                  <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">${ev.timestamp}</div>
                </div>
              `).join("");
        } else {
          title.innerText = "Protective Guidance Advisories";
          subtitle.innerText = "User-safe recommendations from MoneyTrace";
          body.innerHTML = currentNotifications.length === 0
            ? `<div style="font-size:12.5px; color:var(--text-muted);">No advisories yet.</div>`
            : currentNotifications.map(n => `
                <div style="background:var(--bg-subtle); border-radius:var(--radius-xs); padding:12px; cursor:pointer;" onclick="MoneyTraceApp.showNotificationModal('${n.id}')">
                  <strong style="color:var(--brand-dark-navy);">${n.title}</strong>
                  <div style="font-size:12px; color:var(--text-body); margin-top:2px;">${n.summary}</div>
                  <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">${n.created_at} • Click to read advice</div>
                </div>
              `).join("");
        }
      }
    }
  }

  async function showNotificationModal(notifId) {
    const notif = currentNotifications.find(n => n.id === notifId);
    if (!notif) return;

    const modal = document.getElementById("modalContainer");
    modal.style.display = "flex";
    modal.className = "modal-backdrop-frosted";
    modal.innerHTML = `
      <div class="modal-card-elevated" style="max-width:540px;">
        <div class="card-header-clean">
          <div>
            <h3 class="card-title-main">${notif.title}</h3>
            <p class="card-subtitle">Verified Protective Response</p>
          </div>
          <button class="icon-btn" onclick="MoneyTraceApp.closeModal()">&times;</button>
        </div>
        <div style="font-size:13.5px; color:var(--text-body); margin-bottom:16px;">${notif.summary}</div>
        <div style="background:var(--status-success-bg); border:1px solid var(--status-success-border); border-radius:var(--radius-sm); padding:18px;">
          <h4 style="color:#166534; font-size:14px; margin-bottom:10px;">Recommended Protective Actions:</h4>
          <div style="white-space:pre-line; font-size:13px; line-height:1.7; color:#14532D;">
            ${notif.guidance}
          </div>
        </div>
        <button class="btn-primary-dark" style="margin-top:24px; width:100%;" onclick="MoneyTraceApp.closeModal()">I Have Taken These Steps</button>
      </div>
    `;
  }

  async function showEvidenceModal(incidentId) {
    const token = localStorage.getItem("mt_token");
    const res = await fetch(`/api/incidents/${incidentId}`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    const inc = await res.json();
    const pkg = inc.evidence_package || {};

    const modal = document.getElementById("modalContainer");
    modal.style.display = "flex";
    modal.className = "modal-backdrop-frosted";
    modal.innerHTML = `
      <div class="modal-card-elevated" style="max-width:720px;">
        <div class="card-header-clean">
          <div>
            <h3 class="card-title-main">Evidence Package: EVD-${incidentId}</h3>
            <p class="card-subtitle">Sealed forensic package for legal and banking authorities</p>
          </div>
          <button class="icon-btn" onclick="MoneyTraceApp.closeModal()">&times;</button>
        </div>
        <pre style="background:var(--brand-dark-navy); color:#38BDF8; padding:18px; border-radius:var(--radius-sm); font-size:12px; max-height:420px; overflow-y:auto; font-family:monospace;">${JSON.stringify(pkg, null, 2)}</pre>
        <button class="btn-primary-dark" style="margin-top:20px; width:100%;" onclick="MoneyTraceApp.closeModal()">Close Evidence Inspection</button>
      </div>
    `;
  }

  function showSimilarityModal(incidentId, count, beneficiary, exposure) {
    const modal = document.getElementById("modalContainer");
    if (!modal) return;
    modal.style.display = "flex";
    modal.className = "modal-backdrop-frosted";
    modal.innerHTML = `
      <div class="modal-card-elevated" style="max-width:520px; border-top:4px solid var(--brand-cyan);">
        <div class="card-header-clean">
          <div style="display:flex; align-items:center; gap:10px;">
            <div style="width:36px; height:36px; border-radius:var(--radius-sm); background:var(--brand-cyan-subtle); display:flex; align-items:center; justify-content:center; color:var(--brand-cyan-hover); font-size:18px;">
              🔗
            </div>
            <div>
              <h3 class="card-title-main" style="font-size:16px;">Similarities Found</h3>
              <p class="card-subtitle">Cognee Syndicate Intelligence Alert</p>
            </div>
          </div>
          <button class="icon-btn" onclick="MoneyTraceApp.closeModal()">&times;</button>
        </div>

        <p style="font-size:13px; color:var(--text-body); margin:14px 0 18px 0; line-height:1.5;">
          This incident is connected to other reported fraud cases in the syndicate knowledge graph.
        </p>

        <div style="background:var(--bg-subtle); border:1px solid var(--border-subtle); border-radius:var(--radius-sm); padding:16px; display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(0,0,0,0.05); padding-bottom:10px;">
            <span style="font-size:12px; color:var(--text-muted); font-weight:600;">Related Incidents</span>
            <strong style="color:var(--brand-dark-navy); font-size:14px;">${count} connected cases</strong>
          </div>
          ${beneficiary ? `
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(0,0,0,0.05); padding-bottom:10px;">
            <span style="font-size:12px; color:var(--text-muted); font-weight:600;">Shared Entity / Beneficiary</span>
            <code style="background:#FFFFFF; padding:2px 8px; border-radius:4px; font-size:12px; border:1px solid var(--border-subtle); color:var(--brand-dark-navy);">${beneficiary}</code>
          </div>` : ''}
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:12px; color:var(--text-muted); font-weight:600;">Correlated Network Exposure</span>
            <strong style="color:var(--status-critical); font-size:15px; font-weight:800;">₹${Number(exposure || 0).toLocaleString()}</strong>
          </div>
        </div>

        <div style="display:flex; gap:12px; margin-top:22px;">
          <button class="btn-primary-dark" style="flex:1;" onclick="MoneyTraceApp.closeModal(); MoneyTraceApp.navigate('/cases/${incidentId}');">
            View Intelligence Graph & Evidence →
          </button>
          <button class="btn-secondary-light" onclick="MoneyTraceApp.closeModal()">
            Dismiss
          </button>
        </div>
      </div>
    `;
  }

  function closeModal() {
    const modal = document.getElementById("modalContainer");
    if (modal) modal.style.display = "none";
  }

  function showToast(msg) {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = "toast-pill";
    toast.innerHTML = `<span class="pulse-dot-green"></span><span>${msg}</span>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  // ==========================================
  // VIEW 6: EVALUATION & ACCURACY BENCHMARK (/evaluation)
  // ==========================================

  async function renderEvaluationView() {
    const main = document.getElementById("mainApp");
    main.innerHTML = `
      <div class="eval-container">
        <!-- Loading State -->
        <div class="frosted-card" id="evalLoadingCard" style="text-align:center; padding: 48px 24px;">
          <div class="pulse-dot-green" style="margin: 0 auto 16px auto; width:12px; height:12px;"></div>
          <h3 class="card-title-main">Loading Canonical Evaluation Benchmark...</h3>
          <p class="card-subtitle">Retrieving held-out test predictions and mathematical artifacts</p>
        </div>
      </div>
    `;

    try {
      const [sumRes, perClassRes, cmRes, provRes] = await Promise.all([
        fetch("/api/evaluation/summary"),
        fetch("/api/evaluation/per-class"),
        fetch("/api/evaluation/confusion-matrix"),
        fetch("/api/evaluation/provenance")
      ]);

      if (!sumRes.ok) throw new Error("Failed to load evaluation summary");

      const summary = await sumRes.json();
      const perClassData = await perClassRes.json();
      const cmData = await cmRes.json();
      const provData = await provRes.json();

      const manifest = provData.manifest || {};
      const mc = summary.multi_class || {};
      const bf = summary.binary_fraud || {};
      const comp = summary.component_evaluation || {};
      const perClass = perClassData.per_class || {};
      const cm = cmData.confusion_matrix || {};
      const classes = cmData.classes || [];

      // Render Per-Class Table Rows
      let perClassRows = "";
      classes.forEach(c => {
        const stats = perClass[c] || { precision: 0, recall: 0, f1: 0, support: 0 };
        perClassRows += `
          <tr>
            <td><strong style="color:var(--brand-dark-navy);">${c}</strong></td>
            <td style="font-weight:700; color:${stats.precision >= 0.9 ? '#059669' : '#D97706'};">${(stats.precision * 100).toFixed(2)}%</td>
            <td style="font-weight:700; color:${stats.recall >= 0.9 ? '#059669' : '#D97706'};">${(stats.recall * 100).toFixed(2)}%</td>
            <td style="font-weight:800; color:${stats.f1 >= 0.9 ? '#059669' : '#D97706'};">${(stats.f1 * 100).toFixed(2)}%</td>
            <td style="color:var(--text-muted); font-weight:600;">${stats.support}</td>
          </tr>
        `;
      });

      // Render Confusion Matrix
      let cmHeaderCols = classes.map(c => `<th title="${c}">${c.replace('_', ' ').substring(0, 5)}</th>`).join("");
      let cmRows = "";
      classes.forEach(actCls => {
        let cells = "";
        classes.forEach(predCls => {
          const val = cm[actCls] ? (cm[actCls][predCls] || 0) : 0;
          let cellCls = "matrix-cell-zero";
          if (actCls === predCls) cellCls = "matrix-cell-match";
          else if (val > 0) cellCls = "matrix-cell-err";
          cells += `<td class="${cellCls}" title="Actual: ${actCls} | Predicted: ${predCls}">${val}</td>`;
        });
        cmRows += `
          <tr>
            <td style="text-align:left; font-weight:700; background:var(--bg-subtle); padding:6px 10px; white-space:nowrap; border:1px solid var(--border-subtle);">${actCls}</td>
            ${cells}
          </tr>
        `;
      });

      main.innerHTML = `
        <div class="eval-container">
          
          <!-- 1. Evaluation Overview Banner -->
          <div class="eval-header-banner">
            <div>
              <div class="eval-pill-tag">
                <span class="pulse-dot-green"></span>
                Held-Out Blind Test Partition (Seed ${manifest.random_seed || 42})
              </div>
              <h2 style="font-size:22px; font-weight:800; color:var(--brand-dark-navy); margin-top:10px;">
                MoneyTrace Fraud Classification Benchmark v1
              </h2>
              <p style="font-size:13px; color:var(--text-muted); margin-top:4px;">
                Canonical evaluation on ${summary.test_sample_count} out-of-sample test cases across ${classes.length} distinct classes (${summary.total_benchmark_records} total benchmark instances).
              </p>
            </div>
            <div style="text-align:right;">
              <div style="font-size:11.5px; font-weight:700; color:var(--text-muted);">EVALUATION RUN ID</div>
              <div style="font-family:ui-monospace, monospace; font-size:13px; font-weight:800; color:var(--brand-dark-navy);">${summary.run_id}</div>
              <div style="font-size:11.5px; color:var(--text-muted); margin-top:3px;">Executed: ${new Date(summary.timestamp).toLocaleString()}</div>
            </div>
          </div>

          <!-- 2. Primary KPI Grids: Fraud Detection & Multi-Class -->
          <div class="eval-grid-2">
            
            <!-- Fraud Detection (Binary) -->
            <div class="frosted-card">
              <div class="card-header-clean">
                <div>
                  <h3 class="card-title-main">1. Binary Fraud Detection</h3>
                  <p class="card-subtitle">Malicious Fraud vs Legitimate / Wrong Transfer</p>
                </div>
                <span class="status-badge" style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0;">Derived Target</span>
              </div>
              <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-bottom:16px;">
                <div class="metric-stat-card">
                  <span class="metric-stat-val" style="color:#059669;">${(bf.f1 * 100).toFixed(1)}%</span>
                  <span class="metric-stat-label">Fraud F1-Score</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(bf.accuracy * 100).toFixed(1)}%</span>
                  <span class="metric-stat-label">Accuracy</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(bf.recall * 100).toFixed(1)}%</span>
                  <span class="metric-stat-label">Recall (TP: ${bf.tp})</span>
                </div>
              </div>
              <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px;">
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(bf.precision * 100).toFixed(1)}%</span>
                  <span class="metric-stat-label">Precision</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val" style="color:#059669;">${(bf.false_positive_rate * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">False Positive Rate</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val" style="color:#059669;">${(bf.false_negative_rate * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">False Negative Rate</span>
                </div>
              </div>
            </div>

            <!-- Multi-Class Classification -->
            <div class="frosted-card">
              <div class="card-header-clean">
                <div>
                  <h3 class="card-title-main">2. Multi-Class Classification</h3>
                  <p class="card-subtitle">Exact categorization into 7 discrete fraud categories</p>
                </div>
                <span class="status-badge" style="background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;">Primary Benchmark</span>
              </div>
              <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; margin-bottom:16px;">
                <div class="metric-stat-card">
                  <span class="metric-stat-val" style="color:#2563EB;">${(mc.macro_f1 * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">Macro F1 (Unweighted)</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(mc.weighted_f1 * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">Weighted F1</span>
                </div>
              </div>
              <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px;">
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(mc.accuracy * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">Overall Accuracy</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(mc.macro_precision * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">Macro Precision</span>
                </div>
                <div class="metric-stat-card">
                  <span class="metric-stat-val">${(mc.macro_recall * 100).toFixed(2)}%</span>
                  <span class="metric-stat-label">Macro Recall</span>
                </div>
              </div>
            </div>

          </div>

          <!-- 3. Per-Class Table & Confusion Matrix Grid -->
          <div class="eval-grid-2">
            
            <!-- Per-Class Performance Table -->
            <div class="frosted-card">
              <div class="card-header-clean">
                <div>
                  <h3 class="card-title-main">3. Per-Class Results Breakdown</h3>
                  <p class="card-subtitle">Precision, Recall, F1 and Support on blind test set</p>
                </div>
              </div>
              <div style="overflow-x:auto;">
                <table class="table-clean-eval">
                  <thead>
                    <tr>
                      <th>Fraud Class</th>
                      <th>Precision</th>
                      <th>Recall</th>
                      <th>F1-Score</th>
                      <th>Support</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${perClassRows}
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Confusion Matrix Table -->
            <div class="frosted-card">
              <div class="card-header-clean">
                <div>
                  <h3 class="card-title-main">4. Multi-Class Confusion Matrix</h3>
                  <p class="card-subtitle">Rows: Ground Truth | Columns: MoneyTrace Prediction</p>
                </div>
              </div>
              <div style="overflow-x:auto;">
                <table class="matrix-grid-table">
                  <thead>
                    <tr>
                      <th style="text-align:left; background:var(--bg-canvas);">Ground Truth \ Pred</th>
                      ${cmHeaderCols}
                    </tr>
                  </thead>
                  <tbody>
                    ${cmRows}
                  </tbody>
                </table>
              </div>
              <div style="display:flex; justify-content:flex-end; gap:16px; margin-top:12px; font-size:11.5px; color:var(--text-muted);">
                <span><strong style="color:#065F46;">Green</strong> = Correct match (TP)</span>
                <span><strong style="color:#B91C1C;">Red</strong> = Error</span>
              </div>
            </div>

          </div>

          <!-- 4. Component Evaluation & Investigation Analysis -->
          <div class="eval-grid-2">
            
            <!-- Component Evaluation -->
            <div class="frosted-card">
              <div class="card-header-clean">
                <div>
                  <h3 class="card-title-main">5. Subsystem Component Verification</h3>
                  <p class="card-subtitle">Scientific separation of measurable vs unmeasured modules</p>
                </div>
              </div>
              <div style="display:flex; flex-direction:column; gap:12px;">
                
                <div style="padding:14px; background:var(--bg-subtle); border-radius:var(--radius-md); border:1px solid var(--border-subtle);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:13.5px;">MoneyTrace Classification Pipeline</strong>
                    <span class="status-badge" style="background:#ECFDF5; color:#065F46;">MEASURED</span>
                  </div>
                  <p style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                    Multi-modal decision engine evaluating 21 numerical, 10 boolean, 7 categorical, and narrative semantic features. Macro F1: <strong>${(comp.moneytrace_classification.macro_f1 * 100).toFixed(2)}%</strong>.
                  </p>
                </div>

                <div style="padding:14px; background:var(--bg-subtle); border-radius:var(--radius-md); border:1px solid var(--border-subtle);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:13.5px;">Google Gemini AI Investigation</strong>
                    <span class="status-badge" style="background:#ECFDF5; color:#065F46;">MEASURED</span>
                  </div>
                  <p style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                    Evaluated on structured narrative synthesis, severity stratification (Macro F1: <strong>${(comp.gemini_investigation.severity_stratification_macro_f1 * 100).toFixed(2)}%</strong>), and red-flag extraction (F1: <strong>${(comp.gemini_investigation.red_flag_detection_f1 * 100).toFixed(2)}%</strong>).
                  </p>
                </div>

                <div style="padding:14px; background:var(--bg-subtle); border-radius:var(--radius-md); border:1px solid var(--border-subtle);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:13.5px;">Sarvam Cloud Speech-to-Text</strong>
                    <span class="status-badge" style="background:#F1F5F9; color:#64748B;">NOT MEASURED</span>
                  </div>
                  <p style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                    ${comp.sarvam_speech_to_text.reason}
                  </p>
                </div>

                <div style="padding:14px; background:var(--bg-subtle); border-radius:var(--radius-md); border:1px solid var(--border-subtle);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:var(--brand-dark-navy); font-size:13.5px;">Cognee Cloud Graph Syndicate Matching</strong>
                    <span class="status-badge" style="background:#F1F5F9; color:#64748B;">NOT MEASURED</span>
                  </div>
                  <p style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                    ${comp.cognee_graph_syndicate.reason}
                  </p>
                </div>

              </div>
            </div>

            <!-- Methodology & Provenance Details -->
            <div class="frosted-card">
              <div class="card-header-clean">
                <div>
                  <h3 class="card-title-main">6. Dataset Provenance & Anti-Leakage</h3>
                  <p class="card-subtitle">Zero customer data, deterministic generation, strict insulation</p>
                </div>
              </div>
              <div style="display:flex; flex-direction:column; gap:12px; font-size:12.5px; color:var(--brand-dark-navy);">
                <div style="padding:12px; background:#F8FAFC; border-radius:var(--radius-md); border-left:3px solid #2563EB;">
                  <strong>1. Target Insulation:</strong> Ground-truth classes (<code>fraud_class</code>, <code>is_fraud</code>) were strictly withheld from inference. Models receive only numerical, boolean, categorical context and user statement.
                </div>
                <div style="padding:12px; background:#F8FAFC; border-radius:var(--radius-md); border-left:3px solid #059669;">
                  <strong>2. Anti-Leakage Controls:</strong> Legitimate and fraudulent cases deliberately share overlapping transaction amounts (₹150 to ₹45,000) and channels. Narratives avoid artificial 1:1 keyword trivialities.
                </div>
                <div style="padding:12px; background:#F8FAFC; border-radius:var(--radius-md); border-left:3px solid #7C3AED;">
                  <strong>3. Cryptographic Provenance:</strong>
                  <div style="font-family:ui-monospace, monospace; font-size:11px; margin-top:4px; word-break:break-all; color:#475569;">
                    SHA-256: ${manifest.canonical_csv_sha256 || 'd974d2b8a7e7f159ceaa689ec66d4996390d7fda9db549ea49fbe8f2574a6541'}
                  </div>
                </div>

                <div style="margin-top:8px;">
                  <strong style="font-size:12px; color:var(--text-muted); text-transform:uppercase;">Reproducibility Command:</strong>
                  <pre class="code-block-repro" style="margin-top:6px;">python evaluation/generate_dataset.py
python evaluation/evaluator.py</pre>
                </div>
              </div>
            </div>

          </div>

        </div>
      `;

    } catch (err) {
      console.error("Evaluation render failed:", err);
      const main = document.getElementById("mainApp");
      main.innerHTML = `
        <div class="frosted-card" style="text-align:center; padding: 48px;">
          <h3 style="color:#DC2626; font-size:18px;">Failed to load evaluation metrics</h3>
          <p style="color:var(--text-muted); margin-top:8px;">${err.message}</p>
          <button class="btn-primary" onclick="MoneyTraceApp.navigate('/evaluation')" style="margin-top:16px;">Retry</button>
        </div>
      `;
    }
  }

  return {
    init,
    navigate,
    setLanguage,
    toggleVoiceRecord,
    handleScreenshotUpload,
    fillSampleScenario,
    submitReport,
    handleFormLogin,
    quickSelectDemo,
    handleProfileClick,
    logout,
    toggleNotificationsPanel,
    showNotificationModal,
    showEvidenceModal,
    closeModal,
    selectPipelineIncident,
    rerunInvestigation,
    signoffIncident,
    renderEvaluationView,
    showSimilarityModal
  };
})();

window.addEventListener("DOMContentLoaded", MoneyTraceApp.init);

