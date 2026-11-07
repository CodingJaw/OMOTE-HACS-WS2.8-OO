/* OMOTE Manager panel. No build step; uses the HA 2024.9 frontend panel API.
 * Read-only: this module never calls the OMOTE firmware directly.
 */
class OmoteManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._mounted = false;
    this._started = false;
    this._hass = null;
    this._overview = null;
    this._selectedRemote = null;
    this._selectedFile = null;
    this._category = "Scenes";
    this._loading = false;
    this._fileRequest = 0;
    this._capabilityRequest = 0;
    this._capabilityEntry = null;
    this._pairingRequest = 0;
    this._pairingEntry = null;
    this._candidateEntry = null;
    this._candidateRequest = 0;
    this._labEntry = null;
    this._labRequest = 0;
    this._labAvailable = false;
    this.workspace = null;
    // Versioned panel name prevents HA from retaining older custom elements.
  }

  set hass(hass) {
    this._hass = hass;
    if (this._mounted && !this._started) {
      this._started = true;
      void this.loadOverview(false);
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._mounted) return;
    this._mounted = true;
    this.shadowRoot.innerHTML =
      '<link rel="stylesheet" href="/omote_manager_static/panel.css?v=0.1.0-dev24">' +
      '<div class="shell">' +
      '  <header class="masthead">' +
      '    <div><p class="eyebrow">HOME ASSISTANT / OMOTE</p><h1>OMOTE Manager</h1>' +
      '    <p class="subtitle">Central configuration workspace for your OMOTE remotes</p></div>' +
      '    <span class="pill">PROFILE STUDIO</span>' +
      '  </header>' +
      '  <nav class="panel-nav" aria-label="OMOTE Manager sections">' +
      '    <button type="button" id="nav-overview" class="nav-pill active">Overview</button>' +
      '    <button type="button" id="nav-studio" class="nav-pill">Profile Studio</button>' +
      '    <span class="muted">Local drafts only · no firmware writes</span>' +
      '  </nav>' +
      '  <div id="notice" role="status" aria-live="polite"></div>' +
      '  <section class="summary" id="summary"></section>' +
      '  <div class="workspace">' +
      '    <aside class="remotes pane"><div class="section-head"><h2>Remotes</h2>' +
      '      <span class="muted" id="remote-count"></span></div>' +
      '      <div id="remote-list" class="remote-list"></div>' +
      '    </aside>' +
      '    <main class="pane editor">' +
      '      <div class="section-head editor-head">' +
      '        <div><p class="eyebrow">SELECTED DEVICE</p><h2 id="device-title">Select a remote</h2>' +
      '        <p id="device-subtitle" class="muted"></p></div>' +
      '        <div class="actions"><button type="button" id="refresh" class="secondary">Refresh</button>' +
      '        <button type="button" id="backup" class="primary">Back up JSON</button>' +
      '        <button type="button" id="inspect-capabilities" class="secondary">Check firmware safety</button><button type="button" id="inspect-pairing" class="secondary">Check pairing readiness</button></div>' +
      '      </div>' +
      '      <div id="capability-inspector" class="capability-inspector" role="status" aria-live="polite">Select a remote to check firmware security features.</div>' +
      '      <div id="pairing-inspector" class="capability-inspector" role="status" aria-live="polite">Pairing has not been checked. This screen cannot start pairing.</div>' +
      '      <section id="candidate-identity-inspector" class="capability-inspector" aria-label="Local Home Assistant candidate identity">' +
      '        <strong>Home Assistant candidate identity — NOT PAIRED</strong>' +
      '        <p id="candidate-identity-status" role="status" aria-live="polite">Select a remote to inspect local key preparation.</p>' +
      '        <button type="button" id="prepare-ha-candidate" class="secondary" disabled>Prepare HA key locally</button>' +
      '        <p class="muted">No remote pairing or configuration writes. HA local .storage is not encrypted at rest; full HA backups can contain candidate key material.</p>' +
      '      </section>' +
      '      <section id="sec2-lab-inspector" class="capability-inspector" aria-label="Experimental encrypted laboratory test">' +
      '        <strong>Security2 encrypted LAB — NOT PAIRED</strong>' +
      '        <p id="lab-status" role="status" aria-live="polite">Select a remote to inspect LAB prerequisites.</p>' +
      '        <button type="button" id="lab-check" class="secondary" disabled>Check LAB prerequisites</button>' +
      '        <button type="button" id="lab-run" class="secondary" disabled>Run encrypted LAB test</button>' +
      '        <p class="muted">Opt-in experimental mode only. Requires physical Start lab and a fresh six-digit PIN. ' +
      '        No permanent trust, remote configuration writes, OTA, or eFuse changes. Use an HTTPS Home Assistant connection when entering a PIN.</p>' +
      '      </section>' +
      '      <div id="categories" class="categories" aria-label="Configuration categories"></div>' +
      '      <div class="content-grid">' +
      '        <section class="file-pane"><h3>Configuration files</h3><div id="file-list"></div></section>' +
      '        <section class="preview-pane"><div class="preview-head"><h3 id="preview-title">Preview</h3>' +
      '        <span class="muted">Live data • no edits</span></div>' +
      '        <pre id="file-preview" tabindex="0">Select a configuration file to inspect its contents.</pre></section>' +
      '      </div>' +
      '      <div class="footer-note">Settings and credentials are excluded from file previews. ' +
      '      Live JSON previews are read-only; Profile Studio saves editable drafts in Home Assistant. Deployment remains disabled.</div>' +
      '    </main>' +
      '  </div>' +
      '  <section id="studio-load-state" class="pane studio-pending" role="status">' +
      '    <h2>Profile Studio</h2>' +
      '    <p id="studio-loading-message">Loading Profile Studio…</p>' +
      '    <p class="muted">This section manages local draft configurations and does not write to the remote.</p>' +
      '  </section>' +
      '</div>';
    this.shadowRoot.getElementById("refresh").addEventListener("click", () => {
      void this.loadOverview(true);
    });
    this.shadowRoot.getElementById("backup").addEventListener("click", () => {
      void this.backupSelected();
    });
    this.shadowRoot.getElementById("inspect-capabilities").addEventListener("click", () => {
      void this.inspectCapabilities();
    });
    this.shadowRoot.getElementById("inspect-pairing").addEventListener("click", () => {
      void this.inspectPairing();
    });
    this.shadowRoot.getElementById("prepare-ha-candidate").addEventListener("click", () => {
      void this.prepareHaCandidate();
    });
    this.shadowRoot.getElementById("lab-check").addEventListener("click", () => {
      void this.inspectLabReadiness();
    });
    this.shadowRoot.getElementById("lab-run").addEventListener("click", () => {
      void this.runEncryptedLabTest();
    });
    this.shadowRoot.getElementById("nav-overview").addEventListener("click", () => {
      this._navigateTo("overview");
    });
    this.shadowRoot.getElementById("nav-studio").addEventListener("click", () => {
      this._navigateTo("studio");
    });
    this._loadStudio();
    if (this._hass && !this._started) {
      this._started = true;
      void this.loadOverview(false);
    }
  }

  _navigateTo(section) {
    const overviewButton = this.shadowRoot.getElementById("nav-overview");
    const studioButton = this.shadowRoot.getElementById("nav-studio");
    overviewButton.classList.toggle("active", section === "overview");
    studioButton.classList.toggle("active", section === "studio");
    const target = section === "studio"
      ? this.shadowRoot.querySelector(".studio") ||
        this.shadowRoot.getElementById("studio-load-state")
      : this.shadowRoot.querySelector(".workspace");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async _loadStudio() {
    const state = this.shadowRoot.getElementById("studio-load-state");
    try {
      const module = await import("./workspace-panel.js?v=0.1.0-dev24");
      if (!this._mounted) return;
      if (typeof module.attachWorkspace !== "function") {
        throw new Error("Profile Studio module has no initializer");
      }
      this.workspace = module.attachWorkspace(this);
      if (state) state.remove();
    } catch (error) {
      console.error("OMOTE Profile Studio initialization failed", error);
      if (state) {
        state.classList.add("studio-load-error");
        const details = state.querySelector("#studio-loading-message");
        if (details) {
          details.textContent = "Could not initialize Profile Studio: " +
            String(error && error.message || error);
        }
      }
      this._notice("Profile Studio failed to initialize. See the panel error below.", true);
    }
  }

  _notice(message, error) {
    const notice = this.shadowRoot.getElementById("notice");
    notice.textContent = message || "";
    notice.className = message ? (error ? "notice error" : "notice") : "";
  }

  async loadOverview(refresh) {
    if (this._loading || !this._hass) return;
    this._loading = true;
    const refreshButton = this.shadowRoot.getElementById("refresh");
    refreshButton.disabled = true;
    this._notice(refresh ? "Refreshing connected remotes…" : "Loading remote inventory…");
    try {
      this._overview = await this._hass.callWS({
        type: "omote_manager/overview", refresh: Boolean(refresh)
      });
      const remotes = this._overview.remotes || [];
      if (!remotes.some((r) => r.entry_id === this._selectedRemote)) {
        this._selectedRemote = remotes.length ? remotes[0].entry_id : null;
        this._selectedFile = null;
      }
      this.renderOverview();
      if (this.workspace) void this.workspace.refresh();
      this._notice("");
    } catch (error) {
      this._notice("Unable to load OMOTE data: " + String(error.message || error), true);
    } finally {
      this._loading = false;
      refreshButton.disabled = false;
    }
  }

  selectedRemote() {
    if (!this._overview) return null;
    return (this._overview.remotes || []).find(
      (remote) => remote.entry_id === this._selectedRemote
    ) || null;
  }

  _stat(label, value, annotation) {
    const wrapper = document.createElement("div");
    wrapper.className = "stat";
    const name = document.createElement("span");
    name.className = "stat-label";
    name.textContent = label;
    const amount = document.createElement("strong");
    amount.textContent = String(value);
    const note = document.createElement("small");
    note.textContent = annotation;
    wrapper.append(name, amount, note);
    return wrapper;
  }

  renderOverview() {
    const remotes = this._overview ? (this._overview.remotes || []) : [];
    const summary = this.shadowRoot.getElementById("summary");
    summary.replaceChildren(
      this._stat("REGISTERED REMOTES", remotes.length, "Connected to Home Assistant"),
      this._stat("ONLINE", remotes.filter((remote) => remote.online).length, "Available right now"),
      this._stat(
        "JSON FILES",
        remotes.reduce((sum, remote) => sum + (remote.total_files || 0), 0),
        "Across registered remotes"
      )
    );
    this.shadowRoot.getElementById("remote-count").textContent = String(remotes.length);
    this.renderRemotes(remotes);
    this.renderFiles();
  }

  renderRemotes(remotes) {
    const list = this.shadowRoot.getElementById("remote-list");
    list.replaceChildren();
    if (!remotes.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No remotes configured. Add an OMOTE Manager integration under Settings → Devices & services.";
      list.append(empty);
      return;
    }
    for (const remote of remotes) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "remote-button" +
        (remote.entry_id === this._selectedRemote ? " selected" : "");
      button.setAttribute("aria-pressed", String(remote.entry_id === this._selectedRemote));
      const name = document.createElement("span");
      name.className = "remote-name";
      name.textContent = remote.name || remote.host;
      const host = document.createElement("small");
      host.textContent = (remote.host || "Unknown host") + ":" + String(remote.port || 80);
      const state = document.createElement("span");
      state.className = "remote-state " + (remote.online ? "online" : "offline");
      state.textContent = remote.online ? "● Online" : "○ Offline";
      button.append(name, host, state);
      button.addEventListener("click", () => {
        this._selectedRemote = remote.entry_id;
        this._selectedFile = null;
        this._fileRequest += 1;
        this.renderRemotes(remotes);
        this.renderFiles();
        if (this.workspace) this.workspace.onRemoteChanged();
      });
      list.append(button);
    }
  }

  categoryFor(path) {
    if (path === "Scenes.json" || path.startsWith("Scenes/")) return "Scenes";
    const category = path.split("/")[0];
    if (["Pages", "Commands", "Devices", "Actions"].includes(category)) {
      return category;
    }
    return "Other";
  }

  renderFiles() {
    const remote = this.selectedRemote();
    this.shadowRoot.getElementById("device-title").textContent = remote
      ? remote.name : "Select a remote";
    this.shadowRoot.getElementById("device-subtitle").textContent = remote
      ? ((remote.host || "Unknown host") + " · " + (remote.api || "API unavailable")) : "";
    const backup = this.shadowRoot.getElementById("backup");
    backup.disabled = !remote || !remote.online;
    this.shadowRoot.getElementById("inspect-capabilities").disabled =
      !remote || !remote.online;
    this.shadowRoot.getElementById("inspect-pairing").disabled =
      !remote || !remote.online;
    if (this._capabilityEntry !== (remote ? remote.entry_id : null)) {
      this._capabilityEntry = remote ? remote.entry_id : null;
      this._capabilityRequest++;
      this.shadowRoot.getElementById("capability-inspector").textContent =
        remote ? "Select Check firmware safety to inspect read-only capabilities."
          : "Select a remote to inspect its firmware capabilities.";
    }
    if (this._pairingEntry !== (remote ? remote.entry_id : null)) {
      this._pairingEntry = remote ? remote.entry_id : null;
      this._pairingRequest++;
      this.shadowRoot.getElementById("pairing-inspector").textContent =
        remote ? "Select Check pairing readiness. Pairing itself remains disabled."
          : "Select a remote to inspect pairing readiness.";
    }
    if (this._candidateEntry !== (remote ? remote.entry_id : null)) {
      this._candidateEntry = remote ? remote.entry_id : null;
      this._candidateRequest++;
      this.shadowRoot.getElementById("prepare-ha-candidate").disabled = !remote;
      this.shadowRoot.getElementById("candidate-identity-status").textContent =
        remote ? "Checking whether a candidate HA key already exists…"
          : "Select a remote to inspect local key preparation.";
      if (remote) void this.inspectHaCandidate();
    }
    if (this._labEntry !== (remote ? remote.entry_id : null)) {
      this._labEntry = remote ? remote.entry_id : null;
      this._labRequest++;
      this._labAvailable = false;
      this.shadowRoot.getElementById("lab-check").disabled = !remote;
      this.shadowRoot.getElementById("lab-run").disabled = true;
      this.shadowRoot.getElementById("lab-status").textContent =
        remote ? "Check whether this HA host has opted into the Security2 LAB."
          : "Select a remote to inspect LAB prerequisites.";
      if (remote) void this.inspectLabReadiness();
    }
    const categories = this.shadowRoot.getElementById("categories");
    categories.replaceChildren();
    const files = remote ? remote.files || [] : [];
    const categoryNames = ["Scenes", "Pages", "Commands", "Devices", "Actions"];
    for (const label of categoryNames) {
      const count = files.filter((file) => this.categoryFor(file) === label).length;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "category" + (label === this._category ? " active" : "");
      button.textContent = label + " (" + count + ")";
      button.setAttribute("aria-pressed", String(label === this._category));
      button.addEventListener("click", () => {
        this._category = label;
        this._selectedFile = null;
        this._fileRequest += 1;
        this.renderFiles();
      });
      categories.append(button);
    }
    const list = this.shadowRoot.getElementById("file-list");
    list.replaceChildren();
    const visible = files.filter((path) => this.categoryFor(path) === this._category);
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = remote
        ? "No " + this._category.toLowerCase() + " configuration files on this remote."
        : "Select a connected remote to browse configuration files.";
      list.append(empty);
    }
    for (const path of visible) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "file-button" + (path === this._selectedFile ? " selected" : "");
      button.textContent = path.split("/").pop();
      const note = document.createElement("small");
      note.textContent = path;
      button.append(note);
      button.addEventListener("click", () => { void this.readFile(path); });
      list.append(button);
    }
    const preview = this.shadowRoot.getElementById("file-preview");
    const title = this.shadowRoot.getElementById("preview-title");
    if (!this._selectedFile || !files.includes(this._selectedFile)) {
      preview.textContent = "Select a configuration file to inspect its contents.";
      title.textContent = "Preview";
    }
  }

  async readFile(path) {
    if (!this._hass || !this._selectedRemote) return;
    const request = ++this._fileRequest;
    this._selectedFile = path;
    this.renderFiles();
    this.shadowRoot.getElementById("preview-title").textContent = path.split("/").pop();
    const preview = this.shadowRoot.getElementById("file-preview");
    preview.textContent = "Loading " + path + "…";
    try {
      const result = await this._hass.callWS({
        type: "omote_manager/file", entry_id: this._selectedRemote, path: path
      });
      if (request !== this._fileRequest) return;
      let content = result.content;
      try {
        content = JSON.stringify(JSON.parse(content), null, 2);
      } catch (_error) {
        // OMOTE supports JSON files with comments; preserve them as raw text.
      }
      preview.textContent = content;
    } catch (error) {
      if (request !== this._fileRequest) return;
      preview.textContent = "Unable to load file: " + String(error.message || error);
    }
  }


  async inspectCapabilities() {
    const remote = this.selectedRemote();
    if (!remote || !remote.online || !this._hass) return;
    const request = ++this._capabilityRequest;
    const button = this.shadowRoot.getElementById("inspect-capabilities");
    const view = this.shadowRoot.getElementById("capability-inspector");
    button.disabled = true;
    view.textContent = "Reading optional config-v2 capability metadata…";
    try {
      const info = await this._hass.callWS({
        type: "omote_manager/capabilities",
        entry_id: remote.entry_id
      });
      if (request !== this._capabilityRequest ||
          remote.entry_id !== this._selectedRemote) return;
      view.replaceChildren();
      const title = document.createElement("strong");
      title.textContent = info.preview_only
        ? "Firmware: read-only v2 preview"
        : info.generation === "legacy-v1"
          ? "Firmware: legacy configuration API"
          : "Firmware: v2 capability advertisement";
      const values = document.createElement("p");
      values.textContent =
        "API " + info.api_version +
        " · Authentication: " + info.auth_mode +
        " · Transactions: " + (info.transaction_support ? "advertised" : "unavailable") +
        " · Deployment: DISABLED";
      const note = document.createElement("p");
      note.textContent = info.explanation ||
        "Deployments remain disabled until hardware approval.";
      view.append(title, values, note);
      if (info.generation !== "legacy-v1") {
        const storage = info.storage_status || {};
        const diagnostics = document.createElement("p");
        diagnostics.className = "capability-storage";
        if (storage.available) {
          const kib = bytes => (Number(bytes) / 1024).toFixed(0) + " KiB";
          const model = storage.storage_model === "single-active"
            ? "Single active configuration" : "Storage model not advertised";
          const mode = storage.config_mode === "unknown"
            ? "" : " · Mode: " + storage.config_mode;
          diagnostics.textContent = model + mode + " · LittleFS " +
            kib(storage.used_bytes) + " used / " +
            kib(storage.total_bytes) + " total · " +
            kib(storage.estimated_free_bytes) + " estimated free";
          if (storage.active_revision_sha256) {
            const revision = document.createElement("p");
            revision.className = "capability-storage";
            revision.textContent = "Active revision SHA-256: " +
              storage.active_revision_sha256;
            view.append(revision);
          }
          if (storage.recovery_required) {
            const warning = document.createElement("p");
            warning.className = "capability-storage";
            warning.setAttribute("role", "alert");
            warning.textContent = "RECOVERY REQUIRED (" +
              (storage.recovery_reason || "configuration unavailable") +
              "). Check the remote's local recovery screen. " +
              "No automatic resend will occur; manual administrator and " +
              "touchscreen approval are required when secure deployment exists.";
            view.append(warning);
          }
        } else {
          diagnostics.textContent =
            "LittleFS / single-active configuration diagnostics unavailable.";
        }
        view.append(diagnostics);
      }
    } catch (error) {
      if (request !== this._capabilityRequest) return;
      view.textContent =
        "Capability inspection unavailable: " + String(error.message || error) +
        ". No remote configuration was changed.";
    } finally {
      if (request === this._capabilityRequest &&
          remote.entry_id === this._selectedRemote) {
        button.disabled = false;
      }
    }
  }


  async inspectPairing() {
    const remote = this.selectedRemote();
    if (!remote || !remote.online || !this._hass) return;
    const request = ++this._pairingRequest;
    const button = this.shadowRoot.getElementById("inspect-pairing");
    const view = this.shadowRoot.getElementById("pairing-inspector");
    button.disabled = true;
    view.textContent = "Reading read-only pairing readiness…";
    try {
      const info = await this._hass.callWS({
        type: "omote_manager/pairing/status", entry_id: remote.entry_id
      });
      if (request !== this._pairingRequest ||
          remote.entry_id !== this._selectedRemote) return;
      const title = document.createElement("strong");
      title.textContent = info.available
        ? "Firmware pairing API: preliminary Security2 contract"
        : "Firmware pairing API: not available";
      const details = document.createElement("p");
      details.textContent = "Scheme: " + (info.scheme || "none") +
        " · Production encrypted session: NOT AVAILABLE" +
        " · Pairing: DISABLED · Deployment: DISABLED";
      const explanation = document.createElement("p");
      explanation.textContent = info.explanation || "Secure pairing is not available.";
      view.replaceChildren(title, details, explanation);
    } catch (error) {
      if (request !== this._pairingRequest ||
          remote.entry_id !== this._selectedRemote) return;
      view.textContent = "Pairing readiness inspection unavailable: " +
        String(error.message || error) + ". Pairing and deployment remain disabled.";
    } finally {
      if (request === this._pairingRequest &&
          remote.entry_id === this._selectedRemote) button.disabled = false;
    }
  }

  async inspectHaCandidate() {
    const remote = this.selectedRemote();
    if (!remote || !this._hass) return;
    const request = ++this._candidateRequest;
    const view = this.shadowRoot.getElementById("candidate-identity-status");
    try {
      const info = await this._hass.callWS({
        type: "omote_manager/pairing/candidate/status",
        entry_id: remote.entry_id
      });
      if (request !== this._candidateRequest ||
          remote.entry_id !== this._selectedRemote) return;
      if (info.prepared) {
        view.textContent = "Prepared locally; NOT PAIRED. HA public-key SHA-256: " +
          info.fingerprint + ". No remote trust or deployment enabled.";
      } else {
        view.textContent = "No candidate HA key has been prepared. This action " +
          "only creates a per-remote local identity; it cannot pair or deploy.";
      }
    } catch (_error) {
      if (request !== this._candidateRequest ||
          remote.entry_id !== this._selectedRemote) return;
      view.textContent = "Candidate identity storage unavailable or invalid. " +
        "It will not be silently replaced; normal read-only OMOTE remains available.";
      this.shadowRoot.getElementById("prepare-ha-candidate").disabled = true;
    }
  }

  async prepareHaCandidate() {
    const remote = this.selectedRemote();
    const button = this.shadowRoot.getElementById("prepare-ha-candidate");
    if (!remote || !this._hass || button.disabled) return;
    // A separate explicit administrator action prepares only a candidate key.
    // Confirmation is NOT on-device peer approval and can NEVER grant trust.
    if (!window.confirm(
      "Prepare a P-256 HA candidate key for this remote?\n\n" +
      "This is NOT pairing and will not contact or change the remote. " +
      "The private key is stored in local Home Assistant .storage, " +
      "which is NOT encrypted at rest and may be included in HA backups. " +
      "Only proceed if you accept this laboratory-storage limitation."
    )) return;
    const request = ++this._candidateRequest;
    button.disabled = true;
    const view = this.shadowRoot.getElementById("candidate-identity-status");
    view.textContent = "Preparing candidate HA identity in Home Assistant only…";
    try {
      const info = await this._hass.callWS({
        type: "omote_manager/pairing/candidate/prepare",
        entry_id: remote.entry_id
      });
      if (request !== this._candidateRequest ||
          remote.entry_id !== this._selectedRemote) return;
      view.textContent = (info.created ? "Created" : "Already prepared") +
        " local HA candidate identity. SHA-256 public fingerprint: " +
        info.fingerprint + ". NOT PAIRED; no remote writes or deployment.";
    } catch (_error) {
      if (request !== this._candidateRequest ||
          remote.entry_id !== this._selectedRemote) return;
      view.textContent = "Candidate key preparation failed. No remote changes; " +
        "the stored identity must be checked before retrying.";
    } finally {
      if (request === this._candidateRequest &&
          remote.entry_id === this._selectedRemote) button.disabled = false;
    }
  }


  async inspectLabReadiness() {
    const remote = this.selectedRemote();
    if (!remote || !this._hass) return;
    const request = ++this._labRequest;
    const check = this.shadowRoot.getElementById("lab-check");
    const run = this.shadowRoot.getElementById("lab-run");
    const status = this.shadowRoot.getElementById("lab-status");
    check.disabled = true;
    run.disabled = true;
    this._labAvailable = false;
    status.textContent = "Checking opt-in HA laboratory settings…";
    try {
      const info = await this._hass.callWS({
        type: "omote_manager/pairing/lab/readiness",
        entry_id: remote.entry_id
      });
      if (request !== this._labRequest ||
          remote.entry_id !== this._selectedRemote) return;
      this._labAvailable = info.can_attempt === true;
      run.disabled = !this._labAvailable || !remote.online;
      status.textContent = !info.enabled
        ? "LAB disabled on the HA host. To opt in, set OMOTE_SEC2_LAB_ENABLE=1 in the HA Supervisor environment and restart HA. No pairing is enabled."
        : !info.bundled_client_ready
          ? "LAB enabled, but the bundled Security2 client prerequisites failed: " +
            (info.client_diagnostic || "unavailable") + ". No remote attempt was made."
          : !info.registered_lan_ipv4
            ? "LAB requires a registered remote with a private LAN IPv4 address."
            : "Bundled Espressif Security2 client is ready. Physically Start lab on the Waveshare, then run one encrypted test with the screen PIN. NOT PAIRED.";
    } catch (_error) {
      if (request !== this._labRequest ||
          remote.entry_id !== this._selectedRemote) return;
      status.textContent = "LAB diagnostics are unavailable. No pairing or remote write enabled.";
    } finally {
      if (request === this._labRequest &&
          remote.entry_id === this._selectedRemote) check.disabled = false;
    }
  }

  async runEncryptedLabTest() {
    const remote = this.selectedRemote();
    const button = this.shadowRoot.getElementById("lab-run");
    if (!remote || !remote.online || !this._labAvailable || !this._hass ||
        button.disabled) return;
    if (!window.confirm(
      "Run one experimental Security2 LAB exchange on the selected Waveshare?\n\n" +
      "First physically open Settings > SEC2 encrypted LAB test > Start lab. " +
      "Each handshake spends flash-persistent LAB message quota and can require physical Rearm lab. " +
      "The current device software key is NOT hardware protected. " +
      "This test DOES NOT pair or authorize deployment. " +
      "Use an HTTPS Home Assistant connection before entering the PIN."
    )) return;
    let pin = window.prompt("Enter the six-digit code currently shown on the Waveshare (never share or log it):", "");
    if (pin === null) return;
    if (!/^[0-9]{6}$/.test(pin)) {
      pin = "";
      this.shadowRoot.getElementById("lab-status").textContent =
        "A six-digit touchscreen PIN is required. No LAB request was made.";
      return;
    }
    const request = ++this._labRequest;
    const status = this.shadowRoot.getElementById("lab-status");
    button.disabled = true;
    status.textContent = "Performing a single encrypted LAB exchange. Do not repeat unnecessarily…";
    try {
      const result = await this._hass.callWS({
        type: "omote_manager/pairing/lab/test", entry_id: remote.entry_id,
        pin: pin, ack_lab_only: true
      });
      if (request !== this._labRequest ||
          remote.entry_id !== this._selectedRemote) return;
      status.textContent =
        "LAB ONLY: encrypted probe and session-bound identity proofs passed. " +
        "HA public fingerprint: " + result.candidate_ha_fingerprint +
        ". Untrusted Waveshare software-key fingerprint: " +
        result.untrusted_device_fingerprint +
        ". Compare the HA fingerprint with all four rows on the Waveshare, then use Review OK or Reject. " +
        "NOT PAIRED; no trusted credential, config deployment, OTA or eFuse changes.";
    } catch (_error) {
      if (request !== this._labRequest ||
          remote.entry_id !== this._selectedRemote) return;
      status.textContent =
        "LAB attempt could not complete. Review non-secret Home Assistant diagnostics; " +
        "do not retry automatically because the firmware has a persistent message quota. " +
        "No trusted pairing or configuration write was enabled.";
    } finally {
      pin = "";
      if (request === this._labRequest &&
          remote.entry_id === this._selectedRemote) button.disabled = false;
    }
  }

  async backupSelected() {
    const remote = this.selectedRemote();
    if (!remote || !this._hass) return;
    const button = this.shadowRoot.getElementById("backup");
    button.disabled = true;
    this._notice("Saving a configuration snapshot in Home Assistant…");
    try {
      await this._hass.callService("omote_manager", "backup_configuration", {
        entry_id: remote.entry_id
      });
      this._notice("Backup saved in Home Assistant storage. The remote was not modified.");
      if (this.workspace && this.workspace.selectedEntry() === remote.entry_id) {
        void this.workspace.loadBackups();
      }
    } catch (error) {
      this._notice("Backup failed: " + String(error.message || error), true);
    } finally {
      button.disabled = false;
    }
  }
}

// Use a new element tag for each incompatible UI revision. Earlier frontend
// sessions can retain old custom-element constructors until a browser reload.
if (!customElements.get("omote-manager-panel-v24")) {
  customElements.define("omote-manager-panel-v24", OmoteManagerPanel);
}
