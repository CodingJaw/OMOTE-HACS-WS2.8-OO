/* OMOTE Profile Studio for Home Assistant 2024.9.
 * All workspace writes are to HA's private storage, never firmware.
 */
class OmoteWorkspaceStudio {
  constructor(panel) {
    this.panel = panel;
    this.root = panel.shadowRoot;
    this.data = null;
    this.selectedFile = "";
    this.selectedCommand = "";
    this.commands = [];
    this._commandToken = 0;
    this._busy = false;
    this._ready = false;
    this.backupHistory = [];
    this.backupEntry = null;
    this.backupToken = 0;
    this.sceneEditor = null;
    this._build();
    void this._loadSceneEditor();
    void this.refresh();
  }

  hass() { return this.panel._hass; }
  ui(id) { return this.section.querySelector("#" + id); }
  selectedEntry() { return this.panel._selectedRemote; }
  draft() { return this.data && this.data.drafts && this.data.drafts[this.selectedEntry()] || null; }

  _build() {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = "/omote_manager_static/workspace.css?v=0.1.0-dev15";
    this.root.append(stylesheet);
    const section = document.createElement("section");
    section.className = "studio pane";
    section.innerHTML = [
      '<div class="studio-heading">',
      '  <div><p class="eyebrow">CONFIGURATION WORKSPACE</p><h2>Profile Studio</h2>',
      '  <p class="muted">Shared locations, reusable scene templates and local command drafts.</p></div>',
      '  <span class="studio-guard">HA DRAFT ONLY · NO DEVICE WRITES</span></div>',
      '<div id="studio-notice" role="status" aria-live="polite"></div>',
      '<div class="studio-toolbar"><div><strong id="studio-device">No remote selected</strong>',
      '  <p class="muted" id="studio-status">Import a remote to begin editing a local copy.</p></div>',
      '  <div class="studio-buttons"><button id="studio-import" class="primary" type="button">Import remote JSON</button>',
      '  <button id="studio-validate" class="secondary" type="button">Validate draft</button>',
      '  <button id="studio-deploy" type="button" disabled title="Firmware-safe deployment is not implemented">Deploy (unavailable)</button></div></div>',
      '<section class="studio-backup-history" aria-label="Remote backup history">',
      '  <header><div><h3>Verified backup history</h3>',
      '    <p class="muted">Up to three saved JSON subsets per remote. Load into a local draft only.</p></div>',
      '    <button type="button" id="studio-backup-refresh">Refresh history</button></header>',
      '  <div class="studio-backup-actions"><label>Saved backup',
      '    <select id="studio-backup-select"></select></label>',
      '    <button type="button" id="studio-backup-load" disabled>Load backup into local draft</button></div>',
      '  <p id="studio-backup-info" class="muted"></p>',
      '  <p id="studio-backup-message" role="status" aria-live="polite"></p>',
      '  <p class="muted studio-backup-warning">Does not restore anything to the Waveshare.',
      '    Full-device firmware, credentials and image assets are not included.</p>',
      '</section>',
      '<div class="studio-columns">',
      '  <section class="studio-card"><header><h3>1. Locations</h3><span class="muted">Hierarchy</span></header>',
      '    <p class="studio-help">Organize rooms and devices without altering OMOTE firmware JSON.</p>',
      '    <div id="studio-locations" class="studio-list"></div>',
      '    <form id="studio-new-location" class="studio-form">',
      '      <label>Location name<input name="name" maxlength="64" placeholder="e.g. Living Room" required /></label>',
      '      <label>Parent location<select name="parent"></select></label>',
      '      <button type="submit" class="secondary">Add location</button></form></section>',
      '  <section class="studio-card"><header><h3>2. Shared scene templates</h3><span class="muted">Reusable</span></header>',
      '    <p class="studio-help">Save a scene with its page/command dependencies in a reusable library.</p>',
      '    <div id="studio-templates" class="studio-list"></div>',
      '    <form id="studio-new-template" class="studio-form">',
      '      <label>Scene from selected draft<select name="scene" required></select></label>',
      '      <label>Template name<input name="name" maxlength="80" placeholder="e.g. Standard TV" required /></label>',
      '      <label>Location<select name="location"></select></label>',
      '      <button type="submit" class="secondary">Save shared template</button></form>',
      '    <div class="studio-rule"></div>',
      '    <form id="studio-apply-template" class="studio-form">',
      '      <label>Reusable template<select name="template" required></select></label>',
      '      <button type="submit" class="secondary">Copy to selected draft</button>',
      '      <small class="muted">Conflicting filenames are never overwritten.</small></form></section>',
      '  <section class="studio-card studio-command-card"><header><h3>3. Command editor</h3><span class="muted">Local draft</span></header>',
      '    <p class="studio-help">Edit IR or MQTT commands using OMOTE’s existing JSON structure. No commands are sent.</p>',
      '    <form id="studio-command-form" class="studio-form">',
      '      <label>Command file<select name="file"></select></label>',
      '      <label>Command<select name="command"></select></label>',
      '      <label>Execution mode<select name="mode"><option value="IR">IR</option><option value="MQTT">MQTT</option></select></label>',
      '      <label>Protocol<input name="protocol" placeholder="NEC, PANASONIC, PUB, SUB…" maxlength="80" required /></label>',
      '      <label>Data strings, one per line<textarea name="data" rows="5" spellcheck="false"></textarea></label>',
      '      <button type="submit" class="primary">Save command in draft</button>',
      '      <small class="muted">Saving normalizes the edited file’s JSON formatting, removing its comments. Unedited files stay unchanged.</small>',
      '    </form></section></div>',
      '<div class="studio-validation"><div class="studio-validation-heading"><h3>Validation results</h3>',
      '  <span class="muted">Firmware reference checks · deployment disabled</span></div>',
      '  <div id="studio-issues" class="studio-issues">Import a draft and click Validate draft.</div></div>'
    ].join("");
    this.root.querySelector(".shell").append(section);
    this.section = section;

    this.ui("studio-import").addEventListener("click", () => void this.importRemote());
    this.ui("studio-validate").addEventListener("click", () => void this.validate());
    this.ui("studio-backup-refresh").addEventListener("click", () => void this.loadBackups());
    this.ui("studio-backup-load").addEventListener("click", () => void this.loadBackupDraft());
    this.ui("studio-backup-select").addEventListener("change", () => this.renderBackups());
    this.ui("studio-new-location").addEventListener("submit", event => {
      event.preventDefault();
      void this.createLocation(event.currentTarget);
    });
    this.ui("studio-new-template").addEventListener("submit", event => {
      event.preventDefault();
      void this.createTemplate(event.currentTarget);
    });
    this.ui("studio-apply-template").addEventListener("submit", event => {
      event.preventDefault();
      void this.applyTemplate(event.currentTarget);
    });
    this.ui("studio-command-form").addEventListener("submit", event => {
      event.preventDefault();
      void this.saveCommand(event.currentTarget);
    });
    this.ui("studio-command-form").elements.file.addEventListener("change", event => {
      this.selectedFile = event.target.value;
      this.selectedCommand = "";
      void this.loadCommands();
    });
    this.ui("studio-command-form").elements.command.addEventListener("change", event => {
      this.selectedCommand = event.target.value;
      this.renderCommandValues();
    });
  }

  async _loadSceneEditor() {
    try {
      const {attachSceneEditor} = await import("./scene-editor.js?v=0.1.0-dev15");
      this.sceneEditor = attachSceneEditor(this);
    } catch (error) {
      console.error("OMOTE scene/page editor failed to initialize", error);
      this.message("Scene/page editor unavailable: " +
        String(error.message || error), true);
    }
  }

  message(message, error = false) {
    const element = this.ui("studio-notice");
    element.textContent = message || "";
    element.className = message ? (error ? "studio-message error" : "studio-message") : "";
  }

  async refresh() {
    if (!this.hass()) return;
    try {
      this.data = await this.hass().callWS({type: "omote_manager/workspace"});
      this._ready = true;
      this.render();
    } catch (error) {
      this.message("Workspace unavailable: " + String(error.message || error), true);
    }
  }

  async change(message, success) {
    if (this._busy || !this.data) return false;
    this._busy = true;
    this.message("Saving changes in Home Assistant…");
    try {
      this.data = await this.hass().callWS(Object.assign(
        {revision: this.data.revision}, message
      ));
      this.message(success);
      this.render();
      return true;
    } catch (error) {
      this.message(String(error.message || error) + " — refresh if the workspace changed in another session.", true);
      return false;
    } finally {
      this._busy = false;
      this.render();
    }
  }

  option(value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
  }

  select(element, items, chosen) {
    element.replaceChildren();
    for (const [value, label] of items) element.append(this.option(value, label));
    if (items.some(([value]) => value === chosen)) element.value = chosen;
  }

  locations() { return this.data && this.data.locations || []; }

  locationLabel(id) {
    if (!id) return "Shared / all locations";
    const names = [];
    let next = id;
    for (let depth = 0; next && depth < 20; depth++) {
      const found = this.locations().find(l => l.id === next);
      if (!found) break;
      names.unshift(found.name);
      next = found.parent_id;
    }
    return names.join(" / ");
  }

  locationOptions() {
    const locations = this.locations();
    const descend = (parent, depth) => {
      if (depth > 12) return [];
      const children = locations.filter(loc => loc.parent_id === parent)
        .sort((a, b) => a.name.localeCompare(b.name));
      return children.flatMap(loc => [
        [loc.id, "\u00a0\u00a0".repeat(depth) + loc.name],
        ...descend(loc.id, depth + 1)
      ]);
    };
    return [["", "None (top level)"], ...descend(null, 0)];
  }

  onRemoteChanged() {
    this.backupEntry = null;
    this.backupHistory = [];
    ++this.backupToken;
    this.renderBackups();
    if (this.sceneEditor) this.sceneEditor.onRemoteChanged();
    this.selectedFile = "";
    this.selectedCommand = "";
    this.commands = [];
    this._commandToken += 1;
    this.render();
  }

  render() {
    if (!this._ready) return;
    const remote = this.panel.selectedRemote();
    const draft = this.draft();
    this.ui("studio-device").textContent = remote ? (remote.name || remote.host) : "No remote selected";
    this.ui("studio-status").textContent = draft
      ? draft.file_count + " files imported · " + draft.modified_count
        + " modified · SHA-256 " + (draft.current_sha256 || "").slice(0, 12) + "…"
      : "No local draft imported for this remote";
    this.ui("studio-import").disabled = this._busy || !remote || !remote.online;
    this.ui("studio-validate").disabled = this._busy || !draft;
    if (this.backupEntry !== this.selectedEntry()) {
      void this.loadBackups();
    }
    this.renderLocations();
    this.renderTemplates();
    this.renderCommands();
    if (this.sceneEditor) this.sceneEditor.render();
  }

  async loadBackups() {
    const remote = this.selectedEntry();
    const token = ++this.backupToken;
    this.backupEntry = remote;
    this.backupHistory = [];
    this.ui("studio-backup-message").textContent = remote
      ? "Loading saved backup history…" : "";
    this.renderBackups();
    if (!remote || !this.hass()) return;
    try {
      const result = await this.hass().callWS({
        type: "omote_manager/backups/list", entry_id: remote
      });
      if (token !== this.backupToken || this.selectedEntry() !== remote) return;
      this.backupHistory = result.snapshots || [];
      this.ui("studio-backup-message").textContent = "";
    } catch (error) {
      if (token !== this.backupToken) return;
      this.ui("studio-backup-message").textContent =
        "Could not load backups: " + String(error.message || error);
    }
    this.renderBackups();
  }

  renderBackups() {
    const chooser = this.ui("studio-backup-select");
    const selected = chooser.value;
    const backups = this.backupHistory || [];
    this.select(chooser, backups.map(snapshot => [
      String(snapshot.index),
      (snapshot.created_at || "Unknown date") + " · " +
        (snapshot.integrity === "verified" ? "Verified" : "Damaged")
    ]), selected);
    const current = backups.find(item => String(item.index) === chooser.value);
    const valid = current && current.integrity === "verified";
    this.ui("studio-backup-load").disabled = this._busy || !valid;
    chooser.disabled = !backups.length;
    this.ui("studio-backup-refresh").disabled = !this.selectedEntry();
    this.ui("studio-backup-info").textContent = current
      ? (valid
        ? current.file_count + " JSON files · " + current.bytes +
          " bytes · SHA-256 " + current.sha256.slice(0, 16) + "…"
        : "This backup failed its integrity check and cannot be loaded.")
      : this.selectedEntry()
        ? "No saved backups. Use Back up JSON in the Overview section."
        : "Select a remote to view its saved backups.";
  }

  async loadBackupDraft() {
    const current = this.backupHistory.find(item =>
      String(item.index) === this.ui("studio-backup-select").value
    );
    if (!current || current.integrity !== "verified" ||
        !this.selectedEntry() || !this.data) return;
    const entry = this.selectedEntry();
    const existing = Boolean(this.draft());
    if (!window.confirm(
      "Load the saved JSON backup from " + current.created_at +
      " into the HOME ASSISTANT local draft for this remote? " +
      (existing
        ? "This REPLACES all unsent edits currently in that draft. "
        : "") +
      "It does NOT restore, overwrite or restart the physical Waveshare."
    )) return;
    const completed = await this.change({
      type: "omote_manager/backups/load-to-draft",
      entry_id: entry, index: Number(current.index),
      sha256: current.sha256, replace: existing
    }, "Backup copied into the local draft; remote remains unchanged.");
    if (completed) {
      this.selectedFile = "";
      this.selectedCommand = "";
      this.commands = [];
      if (this.sceneEditor) this.sceneEditor.onRemoteChanged();
      this.ui("studio-backup-message").textContent =
        "Integrity-checked backup loaded into Home Assistant draft only.";
      this.ui("studio-issues").textContent =
        "Backup loaded. Run Validate draft before further editing.";
      this.render();
    }
  }

  renderLocations() {
    const list = this.ui("studio-locations");
    list.replaceChildren();
    if (!this.locations().length) {
      const p = document.createElement("p");
      p.className = "studio-empty";
      p.textContent = "No locations yet. Create Home, then Living Room or Bedroom.";
      list.append(p);
    }
    for (const [value, label] of this.locationOptions().slice(1)) {
      const item = document.createElement("div");
      item.className = "studio-item";
      item.textContent = label;
      item.title = this.locationLabel(value);
      item.style.whiteSpace = "pre-wrap";
      list.append(item);
    }
    const parent = this.ui("studio-new-location").elements.parent;
    this.select(parent, this.locationOptions(), parent.value);
  }

  renderTemplates() {
    const draft = this.draft();
    const templates = this.data.templates || [];
    const list = this.ui("studio-templates");
    list.replaceChildren();
    if (!templates.length) {
      const p = document.createElement("p");
      p.className = "studio-empty";
      p.textContent = "No shared templates. Import a draft and save a scene.";
      list.append(p);
    }
    for (const template of templates) {
      const item = document.createElement("div");
      item.className = "studio-item";
      const name = document.createElement("strong");
      name.textContent = template.name;
      const details = document.createElement("small");
      details.textContent = (template.file_count || 0) + " files · " + this.locationLabel(template.location_id);
      item.append(name, details);
      list.append(item);
    }
    const create = this.ui("studio-new-template");
    const scene = create.elements.scene;
    this.select(scene, (draft ? draft.scenes : []).map(s => [s.path, s.name]), scene.value);
    const location = create.elements.location;
    this.select(location, [["", "Shared / all locations"], ...this.locationOptions().slice(1)], location.value);
    create.querySelector("button").disabled = !draft || !(draft.scenes || []).length;
    const apply = this.ui("studio-apply-template");
    this.select(apply.elements.template, templates.map(t => [
      t.id, t.name + " (" + (t.file_count || 0) + " files)"
    ]), apply.elements.template.value);
    apply.querySelector("button").disabled = !draft || !templates.length;
  }

  renderCommands() {
    const draft = this.draft();
    const form = this.ui("studio-command-form");
    const fileSelect = form.elements.file;
    const files = draft ? draft.command_files : [];
    this.select(fileSelect, files.map(path => [path, path.split("/").pop()]), this.selectedFile);
    const chosen = fileSelect.value || "";
    if (chosen !== this.selectedFile) {
      this.selectedFile = chosen;
      this.selectedCommand = "";
      this.commands = [];
      if (chosen) void this.loadCommands();
    }
    form.querySelector("button[type=submit]").disabled = !draft || !this.commands.length || this._busy;
    this.renderCommandList();
  }

  renderCommandList() {
    const form = this.ui("studio-command-form");
    const select = form.elements.command;
    this.select(select, this.commands.filter(c =>
      c && typeof c.Command === "string").map(c => [c.Command, c.Command]), this.selectedCommand);
    this.selectedCommand = select.value || "";
    this.renderCommandValues();
  }

  renderCommandValues() {
    const form = this.ui("studio-command-form");
    const command = this.commands.find(c => c && c.Command === this.selectedCommand);
    if (!command) {
      form.elements.protocol.value = "";
      form.elements.data.value = "";
      form.querySelector("button[type=submit]").disabled = true;
      return;
    }
    form.elements.mode.value = ["IR", "MQTT"].includes(command.Mode) ? command.Mode : "IR";
    form.elements.protocol.value = command.Protocol || "";
    form.elements.data.value = Array.isArray(command.Data) ? command.Data.join("\n") : "";
    form.querySelector("button[type=submit]").disabled = this._busy;
  }

  async loadCommands() {
    const token = ++this._commandToken;
    const entry = this.selectedEntry();
    const path = this.selectedFile;
    if (!entry || !path || !this.draft()) return;
    try {
      const result = await this.hass().callWS({
        type: "omote_manager/workspace/commands", entry_id: entry, path
      });
      if (token !== this._commandToken || entry !== this.selectedEntry()) return;
      this.commands = result.commands || [];
      this.renderCommandList();
    } catch (error) {
      if (token !== this._commandToken) return;
      this.commands = [];
      this.renderCommandList();
      this.message("Could not load commands: " + String(error.message || error), true);
    }
  }

  async importRemote() {
    if (!this.data || !this.selectedEntry()) return;
    const draft = this.draft();
    if (draft && !window.confirm(
      "Replace the local draft with a fresh copy from the remote? All unsent draft edits will be lost. The remote will not change."
    )) return;
    const success = await this.change({
      type: "omote_manager/workspace/import",
      entry_id: this.selectedEntry(),
      replace: Boolean(draft)
    }, "Remote JSON imported into Home Assistant. No firmware files changed.");
    if (success) {
      this.selectedFile = "";
      this.selectedCommand = "";
      this.commands = [];
      if (this.sceneEditor) this.sceneEditor.onRemoteChanged();
      this.ui("studio-issues").textContent = "Imported. Run validation to check references.";
      this.render();
    }
  }

  async createLocation(form) {
    const name = form.elements.name.value.trim();
    if (!name) return;
    const success = await this.change({
      type: "omote_manager/workspace/location",
      name, parent_id: form.elements.parent.value || null
    }, "Location created.");
    if (success) form.elements.name.value = "";
  }

  async createTemplate(form) {
    if (!this.draft() || !this.selectedEntry()) return;
    const scenePath = form.elements.scene.value;
    const name = form.elements.name.value.trim();
    if (!name || !scenePath) return;
    const success = await this.change({
      type: "omote_manager/workspace/template",
      entry_id: this.selectedEntry(), name,
      scene_path: scenePath, location_id: form.elements.location.value || null
    }, "Reusable template saved to Home Assistant.");
    if (success) form.elements.name.value = "";
  }

  async applyTemplate(form) {
    const templateId = form.elements.template.value;
    if (!templateId || !this.draft()) return;
    const template = (this.data.templates || []).find(t => t.id === templateId);
    if (!template) return;
    if (!window.confirm(
      "Copy '" + template.name + "' to this remote's LOCAL draft? " +
      "Conflicting filenames will be rejected. No firmware files will change."
    )) return;
    const success = await this.change({
      type: "omote_manager/workspace/apply-template",
      entry_id: this.selectedEntry(), template_id: templateId
    }, "Template copied into local draft. Validate before any future deployment.");
    if (success) {
      if (this.sceneEditor) this.sceneEditor.onRemoteChanged();
      this.ui("studio-issues").textContent = "Template added to draft. Run validation.";
    }
  }

  async saveCommand(form) {
    if (!this.draft() || !this.selectedFile || !this.selectedCommand) return;
    const success = await this.change({
      type: "omote_manager/workspace/edit-command",
      entry_id: this.selectedEntry(),
      path: this.selectedFile, name: this.selectedCommand,
      mode: form.elements.mode.value,
      protocol: form.elements.protocol.value.trim(),
      data: form.elements.data.value.replace(/\r/g, "").split("\n")
    }, "Command saved in local draft. No firmware configuration changed.");
    if (success) {
      this.ui("studio-issues").textContent = "Draft changed. Run validation.";
      await this.loadCommands();
    }
  }

  async validate() {
    if (!this.draft()) return;
    this.ui("studio-issues").textContent = "Checking JSON and file references…";
    try {
      const result = await this.hass().callWS({
        type: "omote_manager/workspace/validate", entry_id: this.selectedEntry()
      });
      const issues = result.issues || [];
      const container = this.ui("studio-issues");
      container.replaceChildren();
      const summary = document.createElement("p");
      summary.className = result.errors ? "studio-validation-error" : "studio-validation-ok";
      summary.textContent = result.errors + " errors · " + result.warnings +
        " warnings · draft hash " + String(result.sha256 || "").slice(0, 12) + "…";
      container.append(summary);
      if (!issues.length) {
        const p = document.createElement("p");
        p.textContent = "Structural checks passed. Deployment remains disabled until firmware safeguards are available.";
        container.append(p);
      }
      for (const issue of issues.slice(0, 100)) {
        const item = document.createElement("div");
        item.className = "studio-issue " + (issue.level === "error" ? "is-error" : "is-warning");
        const head = document.createElement("strong");
        head.textContent = issue.level.toUpperCase() + " · " + (issue.path || "Workspace");
        const msg = document.createElement("span");
        msg.textContent = issue.message;
        item.append(head, msg);
        container.append(item);
      }
    } catch (error) {
      this.ui("studio-issues").textContent = "Validation failed: " + String(error.message || error);
    }
  }
}

export function attachWorkspace(panel) {
  return new OmoteWorkspaceStudio(panel);
}
