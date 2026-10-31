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
      '<link rel="stylesheet" href="/omote_manager_static/panel.css?v=0.1.0-dev5">' +
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
      '        <button type="button" id="backup" class="primary">Back up JSON</button></div>' +
      '      </div>' +
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
      const module = await import("./workspace-panel.js?v=0.1.0-dev5");
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
    } catch (error) {
      this._notice("Backup failed: " + String(error.message || error), true);
    } finally {
      button.disabled = false;
    }
  }
}

// Use a new element tag for each incompatible UI revision. Earlier frontend
// sessions can retain old custom-element constructors until a browser reload.
if (!customElements.get("omote-manager-panel-v5")) {
  customElements.define("omote-manager-panel-v5", OmoteManagerPanel);
}
