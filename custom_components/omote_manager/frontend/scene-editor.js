/* Draft-only OMOTE scene, page and button editor. No firmware writes. */
class SceneEditor {
  constructor(studio) {
    this.studio = studio;
    this.scenePath = "";
    this.pageIndex = 0;
    this.widgetIndex = 0;
    this.detail = null;
    this.diffPath = "";
    this.token = 0;
    this.diffToken = 0;
    this.diffData = null;
    this.reviewHash = null;
    this.reviewToken = 0;
    this.reviewRevision = null;
    this.reviewCheckedLive = null;
    this.reviewValid = false;
    this.busy = false;
    this.layoutEditor = null;
    this.create();
    void this.loadLayoutEditor();
    this.render();
  }

  get entryId() { return this.studio.selectedEntry(); }
  get draft() { return this.studio.draft(); }
  get page() { return this.detail?.pages?.find(p => p.index === this.pageIndex); }
  ui(id) { return this.section.querySelector("#" + id); }

  create() {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "/omote_manager_static/scene-editor.css?v=0.1.0-dev10";
    this.studio.root.append(css);
    const section = document.createElement("section");
    section.className = "scene-editor";
    section.innerHTML = [
      '<header><div><p class="eyebrow">CONFIGURATION EDITOR</p>',
      '<h3>4. Scenes, pages &amp; button assignments</h3>',
      '<p class="muted">Only Home Assistant drafts are changed. The remote remains untouched.</p></div>',
      '<span class="muted">Draft only</span></header>',
      '<p id="se-message" role="status" aria-live="polite"></p>',
      '<div class="se-pickers"><label>Scene<select id="se-scene"></select></label>',
      '<label>Page<select id="se-page"></select></label></div>',
      '<p id="se-path" class="muted"></p>',
      '<div class="se-grid">',
      '<form id="se-scene-form"><h4>Scene metadata</h4>',
      '<label>Menu name<input name="name" maxlength="80" required></label>',
      '<label>Screen title<input name="screen_name" maxlength="80" required></label>',
      '<label>Launch key<select name="bind_key"></select></label>',
      '<label>Press type<select name="press_type"></select></label>',
      '<button type="submit">Save scene</button></form>',
      '<form id="se-page-form"><h4>Page / tab labels</h4>',
      '<label>Page name<input name="name" maxlength="80" required></label>',
      '<label>Tab name<input name="short_name" maxlength="32"></label>',
      '<button type="submit">Save page labels</button>',
      '<small>Labels belong to this scene; page JSON may be shared.</small></form>',
      '<form id="se-widget-form"><h4>Touchscreen widgets</h4>',
      '<label>Widget<select name="widget"></select></label>',
      '<label>Field<select name="field"></select></label>',
      '<label id="se-slot-wrap">Array position<select name="slot"></select></label>',
      '<label id="se-text-wrap">Caption<input name="text" maxlength="100"></label>',
      '<label id="se-command-wrap">Command<select name="command"></select></label>',
      '<button type="submit">Save widget</button>',
      '<small>Editing a page changes every scene using that same page file.</small></form>',
      '<form id="se-key-form"><h4>Physical button mapping</h4>',
      '<label>Key<select name="key"></select></label>',
      '<label>Event<select name="event"></select></label>',
      '<label>Command<select name="command"></select></label>',
      '<button type="submit">Save mapping</button>',
      '<small>Choose “No assignment” to remove this key/event mapping.</small></form>',
      '</div>',
      '<div class="se-diff"><header><h4>5. Compare original and draft</h4>',
      '<button type="button" id="se-refresh-diff">Refresh comparison</button></header>',
      '<div class="se-diff-controls"><label>Modified file<select id="se-diff-file"></select></label>',
      '<button id="se-revert" type="button" disabled>Revert draft file</button></div>',
      '<div class="se-diff-toolbar">',
      '  <div class="se-diff-legend" aria-label="Change colors">',
      '    <span class="se-legend-add">+ Added (green)</span>',
      '    <span class="se-legend-remove">− Removed (red)</span>',
      '    <span class="se-legend-hunk">@@ Section (blue)</span>',
      '  </div>',
      '  <label class="se-diff-filter"><input id="se-only-changes" type="checkbox">',
      '    Hide unchanged lines</label>',
      '</div>',
      '<p id="se-diff-counts" class="se-diff-counts" aria-live="polite"></p>',
      '<pre id="se-diff" tabindex="0">No modifications since import.</pre>',
      '<div class="se-review">',
      '  <div class="se-review-heading"><div><h4>6. Deployment readiness review</h4>',
      '    <p class="muted">Compare changed draft files against the original import and the live remote.</p></div>',
      '    <button type="button" id="se-review-run">Run review</button></div>',
      '  <label class="se-review-live"><input type="checkbox" id="se-review-check-live" checked>',
      '    Read changed files from Waveshare to check for conflicts</label>',
      '  <div id="se-review-report" class="se-review-report" role="status" aria-live="polite">',
      '    No review performed yet. Remote files will never be written by this check.',
      '  </div>',
      '  <div class="se-kit-export">',
      '    <div><strong>Deployment &amp; rollback package</strong>',
      '      <p>Download proposed JSON, original imported files and a SHA-256 manifest.',
      '      This is not an installable firmware image.</p></div>',
      '    <button type="button" id="se-kit-download" disabled>Download reviewed ZIP</button>',
      '  </div>',
      '  <p id="se-kit-status" role="status" aria-live="polite"></p>',
      '</div>',
      '<small>All comparisons, downloads and reviews are read-only. Remote deployment remains disabled.</small></div>'
    ].join("");
    const validation = this.studio.section.querySelector(".studio-validation");
    validation.parentNode.insertBefore(section, validation);
    this.section = section;
    this.ui("se-scene").addEventListener("change", e => {
      this.scenePath = e.target.value;
      this.pageIndex = 0;
      this.widgetIndex = 0;
      void this.loadScene();
    });
    this.ui("se-page").addEventListener("change", e => {
      this.pageIndex = Number(e.target.value);
      this.widgetIndex = 0;
      this.showPage();
    });
    for (const [id, fn] of [
      ["se-scene-form", () => this.saveScene()],
      ["se-page-form", () => this.savePage()],
      ["se-widget-form", () => this.saveWidget()],
      ["se-key-form", () => this.saveKey()],
    ]) {
      this.ui(id).addEventListener("submit", e => { e.preventDefault(); void fn(); });
    }
    const widget = this.ui("se-widget-form");
    widget.elements.widget.addEventListener("change", e => {
      this.widgetIndex = Number(e.target.value);
      this.showWidget();
    });
    widget.elements.field.addEventListener("change", () => this.showWidget());
    widget.elements.slot.addEventListener("change", () => this.showWidget(false));
    const key = this.ui("se-key-form");
    key.elements.key.addEventListener("change", () => this.showKey());
    key.elements.event.addEventListener("change", () => this.showKey());
    this.ui("se-refresh-diff").addEventListener("click", () => void this.refreshDiff());
    this.ui("se-diff-file").addEventListener("change", e => {
      this.diffPath = e.target.value;
      void this.loadDiff();
    });
    this.ui("se-revert").addEventListener("click", () => void this.revert());
    this.ui("se-only-changes").addEventListener("change", () => this.renderDiff());
    this.ui("se-review-run").addEventListener("click", () => void this.runReview());
    this.ui("se-kit-download").addEventListener("click", () => void this.downloadKit());
    this.ui("se-review-check-live").addEventListener("change", () => {
      this.clearReview("Review preference changed. Run review again before downloading.");
    });
  }

  select(el, items, chosen) {
    el.replaceChildren();
    for (const [value, label] of items) {
      const opt = document.createElement("option");
      opt.value = String(value);
      opt.textContent = String(label);
      el.append(opt);
    }
    if (items.some(([value]) => String(value) === String(chosen))) {
      el.value = String(chosen);
    }
  }

  note(message, error = false) {
    const el = this.ui("se-message");
    el.textContent = message;
    el.className = error ? "se-error" : "";
  }

  enable(id, allowed) {
    for (const field of this.ui(id).querySelectorAll("input, select, button")) {
      field.disabled = !allowed || this.busy;
    }
  }

  async loadLayoutEditor() {
    try {
      const module = await import("./layout-editor.js?v=0.1.0-dev10");
      this.layoutEditor = module.attachVisualLayoutEditor(this);
      this.layoutEditor.render();
    } catch (error) {
      console.error("OMOTE visual layout editor failed to initialize", error);
      this.note("Visual layout editor unavailable: " + String(error.message || error), true);
    }
  }

  onRemoteChanged() {
    this.scenePath = "";
    this.pageIndex = 0;
    this.widgetIndex = 0;
    this.detail = null;
    this.diffPath = "";
    this.diffData = null;
    this.reviewHash = null;
    this.reviewRevision = null;
    this.reviewCheckedLive = null;
    this.reviewValid = false;
    ++this.reviewToken;
    this.ui("se-review-report").textContent = "Select a remote and run the review.";
    this.ui("se-kit-download").disabled = true;
    this.ui("se-kit-status").textContent = "";
    if (this.layoutEditor) this.layoutEditor.onRemoteChanged();
    ++this.token;
    ++this.diffToken;
    this.render();
  }

  render() {
    const scenes = this.draft?.scenes || [];
    const currentHash = this.draft?.current_sha256 || null;
    if (this.reviewHash && this.reviewHash !== currentHash) {
      this.clearReview("Draft changed since the last review. Run it again.");
    }
    if (!scenes.some(scene => scene.path === this.scenePath)) {
      this.scenePath = scenes[0]?.path || "";
      this.pageIndex = 0;
      this.detail = null;
    }
    this.select(this.ui("se-scene"),
      scenes.map(scene => [scene.path, scene.name]), this.scenePath);
    this.ui("se-scene").disabled = !scenes.length;
    if (!this.scenePath) {
      this.ui("se-path").textContent = "Import remote JSON to enable editing.";
      this.detail = null;
      for (const form of ["se-scene-form","se-page-form","se-widget-form","se-key-form"]) {
        this.enable(form, false);
      }
      if (this.layoutEditor) this.layoutEditor.render();
    } else if (!this.detail || this.detail.scene_path !== this.scenePath) {
      void this.loadScene();
    }
    void this.refreshDiff();
  }

  async loadScene() {
    const token = ++this.token;
    const scene = this.scenePath;
    const entry = this.entryId;
    this.detail = null;
    if (!scene || !entry || !this.draft) return;
    this.ui("se-path").textContent = "Loading draft scene…";
    try {
      const result = await this.studio.hass().callWS({
        type: "omote_manager/editor/scene", entry_id: entry, path: scene
      });
      if (token !== this.token || entry !== this.entryId) return;
      this.detail = result.scene;
      if (!this.detail.pages.some(p => p.index === this.pageIndex)) this.pageIndex = 0;
      this.showScene();
      this.showPage();
    } catch (error) {
      if (token === this.token) this.note(
        "Scene load failed: " + String(error.message || error), true
      );
    }
  }

  showScene() {
    if (!this.detail) return;
    const scene = this.detail;
    const form = this.ui("se-scene-form");
    this.enable("se-scene-form", true);
    form.elements.name.value = scene.scene_name;
    form.elements.screen_name.value = scene.screen_name;
    this.select(form.elements.bind_key, [
      ["", "No shortcut"], ...scene.keys.map(key => [key, key])
    ], scene.bind_to_key);
    this.select(form.elements.press_type, scene.event_types.map(event =>
      [event, event]), scene.press_type);
    this.select(this.ui("se-page"), scene.pages.map(page => [
      page.index, page.name + " (" + page.short_name + ")"
    ]), this.pageIndex);
    this.ui("se-page").disabled = !scene.pages.length;
    this.ui("se-path").textContent = scene.scene_path;
  }

  showPage() {
    const page = this.page;
    for (const id of ["se-page-form", "se-widget-form", "se-key-form"]) {
      this.enable(id, Boolean(page));
    }
    if (!page) {
      if (this.layoutEditor) this.layoutEditor.render();
      return;
    }
    const form = this.ui("se-page-form");
    form.elements.name.value = page.name;
    form.elements.short_name.value = page.short_name;
    this.ui("se-path").textContent =
      this.scenePath + " → " + page.path + " → " + page.command_file +
      (page.command_prefix ? " (prefix " + page.command_prefix + ")" : "");
    const widgetForm = this.ui("se-widget-form");
    const widgets = page.widgets.filter(w => w.editable_text || w.editable_command);
    this.select(widgetForm.elements.widget, widgets.map(w => [
      w.index, "#" + (w.index + 1) + " " + w.type + " " + (w.text || "")
    ]), this.widgetIndex);
    this.widgetIndex = Number(widgetForm.elements.widget.value || 0);
    this.showWidget();
    const keyForm = this.ui("se-key-form");
    this.select(keyForm.elements.key, this.detail.keys.map(key => [key,key]),
      keyForm.elements.key.value || "Power");
    this.select(keyForm.elements.event,
      this.detail.event_types.map(event => [event,event]),
      keyForm.elements.event.value || "Press");
    this.showKey();
    if (this.layoutEditor) this.layoutEditor.render();
  }

  showWidget(resetSlot = true) {
    const page = this.page;
    if (!page) return;
    const form = this.ui("se-widget-form");
    const widget = page.widgets.find(w => w.index === this.widgetIndex);
    if (!widget) {
      form.querySelector("button[type=submit]").disabled = true;
      return;
    }
    const choices = [
      ...(widget.editable_text ? [["text","Caption"]] : []),
      ...(widget.editable_command ? [["command","Command"]] : []),
    ];
    this.select(form.elements.field, choices, form.elements.field.value);
    const editingCommand = form.elements.field.value === "command";
    this.ui("se-text-wrap").hidden = editingCommand;
    this.ui("se-command-wrap").hidden = !editingCommand;
    const commands = Array.isArray(widget.command) ? widget.command : [widget.command];
    this.ui("se-slot-wrap").hidden = !editingCommand || !Array.isArray(widget.command);
    this.select(form.elements.slot, commands.map((cmd, ix) => [
      ix, "Position " + (ix+1)
    ]), resetSlot ? 0 : form.elements.slot.value);
    const selectedCommand = commands[Number(form.elements.slot.value || 0)] || "";
    this.select(form.elements.command,
      page.command_options.map(cmd => [cmd,cmd]), selectedCommand);
    form.elements.text.value = typeof widget.text === "string" ? widget.text : "";
    form.querySelector("button[type=submit]").disabled =
      this.busy || (editingCommand && !page.command_options.length);
  }

  showKey() {
    const page = this.page;
    if (!page) return;
    const form = this.ui("se-key-form");
    const value = page.button_maps[form.elements.key.value]?.[form.elements.event.value] || "";
    this.select(form.elements.command, [
      ["", "No assignment"], ...page.command_options.map(cmd => [cmd,cmd])
    ], value);
  }

  async change(message, messageOnSuccess) {
    if (!this.draft || this.busy) return false;
    this.busy = true;
    const good = await this.studio.change({
      ...message, entry_id: this.entryId
    }, messageOnSuccess);
    this.busy = false;
    if (good) {
      this.clearReview("Draft changed. Run deployment review again.");
      await this.loadScene();
      await this.refreshDiff();
      this.studio.ui("studio-issues").textContent =
        "Draft modified. Run Validate draft again.";
    }
    return good;
  }

  async saveScene() {
    if (!this.detail) return;
    const f = this.ui("se-scene-form").elements;
    if (await this.change({
      type: "omote_manager/editor/edit-scene", path: this.scenePath,
      name: f.name.value, screen_name: f.screen_name.value,
      bind_key: f.bind_key.value, press_type: f.press_type.value
    }, "Scene saved to draft.")) this.note("Scene saved.");
  }

  async savePage() {
    if (!this.page) return;
    const f = this.ui("se-page-form").elements;
    if (await this.change({
      type: "omote_manager/editor/edit-page",
      scene_path: this.scenePath, page_index: this.pageIndex,
      name: f.name.value, short_name: f.short_name.value
    }, "Page labels saved to draft.")) this.note("Page labels saved.");
  }

  async saveWidget() {
    if (!this.page) return;
    const f = this.ui("se-widget-form").elements;
    const field = f.field.value;
    if (await this.change({
      type: "omote_manager/editor/edit-widget",
      scene_path: this.scenePath, page_index: this.pageIndex,
      widget_index: this.widgetIndex, field,
      value: field === "text" ? f.text.value : f.command.value,
      command_index: Number(f.slot.value || 0)
    }, "Widget saved to draft.")) this.note("Widget saved.");
  }

  async saveKey() {
    if (!this.page) return;
    const f = this.ui("se-key-form").elements;
    if (await this.change({
      type: "omote_manager/editor/edit-button",
      scene_path: this.scenePath, page_index: this.pageIndex,
      key: f.key.value, event: f.event.value, command: f.command.value
    }, "Physical key mapping saved to draft.")) this.note("Button mapping saved.");
  }

  async refreshDiff() {
    const token = ++this.diffToken;
    const entry = this.entryId;
    if (!entry || !this.draft) {
      this.diffData = null;
      this.ui("se-diff-counts").textContent = "";
      this.select(this.ui("se-diff-file"), [], "");
      this.ui("se-diff").textContent = "Import a remote configuration first.";
      this.ui("se-revert").disabled = true;
      return;
    }
    try {
      const result = await this.studio.hass().callWS({
        type: "omote_manager/editor/diff", entry_id: entry
      });
      if (token !== this.diffToken || entry !== this.entryId) return;
      const changed = result.changed_files || [];
      if (!changed.includes(this.diffPath)) this.diffPath = changed[0] || "";
      this.select(this.ui("se-diff-file"),
        changed.map(path => [path,path]), this.diffPath);
      this.ui("se-revert").disabled = !changed.length;
      if (this.diffPath) void this.loadDiff();
      else {
        this.diffData = null;
        this.ui("se-diff-counts").textContent = "0 added · 0 removed";
        this.ui("se-diff").textContent = "No changes since import.";
      }
    } catch (error) {
      if (token === this.diffToken) this.ui("se-diff").textContent =
        "Comparison failed: " + String(error.message || error);
    }
  }

  async loadDiff() {
    const token = ++this.diffToken;
    const path = this.diffPath;
    const entry = this.entryId;
    if (!entry || !path) return;
    this.ui("se-diff").textContent = "Comparing files…";
    try {
      const result = await this.studio.hass().callWS({
        type: "omote_manager/editor/diff", entry_id: entry, path
      });
      if (token !== this.diffToken || entry !== this.entryId || path !== this.diffPath) return;
      this.diffData = result;
      this.renderDiff();
    } catch (error) {
      if (token === this.diffToken) this.ui("se-diff").textContent =
        "Comparison failed: " + String(error.message || error);
    }
  }

  renderDiff() {
    const preview = this.ui("se-diff");
    const data = this.diffData;
    if (!data) return;
    preview.replaceChildren();
    const onlyChanges = this.ui("se-only-changes").checked;
    let added = 0;
    let removed = 0;
    // Preserve exact diff contents via textContent; do not parse JSON as HTML.
    for (const line of (data.diff || "").split("\n")) {
      if (!line && !data.truncated) continue;
      const header = line.startsWith("--- ") || line.startsWith("+++ ");
      const hunk = line.startsWith("@@");
      const isAdd = !header && line.startsWith("+");
      const isRemove = !header && line.startsWith("-");
      const context = !header && !hunk && !isAdd && !isRemove;
      if (isAdd) added++;
      if (isRemove) removed++;
      if (onlyChanges && context) continue;
      const node = document.createElement("span");
      node.className = "se-diff-line " + (
        header ? "se-diff-file-header" :
        hunk ? "se-diff-hunk" :
        isAdd ? "se-diff-add" :
        isRemove ? "se-diff-remove" : "se-diff-context"
      );
      node.textContent = line || " ";
      preview.append(node);
    }
    if (data.truncated) {
      const notice = document.createElement("span");
      notice.className = "se-diff-line se-diff-truncated";
      notice.textContent = "… Diff truncated at 30,000 characters.";
      preview.append(notice);
    }
    this.ui("se-diff-counts").textContent =
      added + " added · " + removed + " removed" +
      (data.truncated ? " · counts refer to visible diff only" : "");
  }

  clearReview(message) {
    this.reviewHash = null;
    this.reviewRevision = null;
    this.reviewCheckedLive = null;
    this.reviewValid = false;
    ++this.reviewToken;
    this.ui("se-review-report").textContent = message;
    this.ui("se-kit-download").disabled = true;
    this.ui("se-kit-status").textContent = "";
  }

  async runReview() {
    if (!this.draft || !this.entryId) {
      this.clearReview("Import a remote before reviewing its draft.");
      return;
    }
    const reportElement = this.ui("se-review-report");
    const token = ++this.reviewToken;
    const entry = this.entryId;
    const button = this.ui("se-review-run");
    button.disabled = true;
    this.reviewValid = false;
    this.reviewHash = null;
    this.reviewRevision = null;
    this.ui("se-kit-download").disabled = true;
    this.ui("se-kit-status").textContent = "";
    reportElement.textContent = "Checking draft validation, file hashes and remote drift…";
    try {
      const answer = await this.studio.hass().callWS({
        type: "omote_manager/editor/preflight",
        entry_id: entry,
        check_live: this.ui("se-review-check-live").checked
      });
      if (token !== this.reviewToken || entry !== this.entryId) return;
      this.reviewHash = answer.draft_sha256;
      this.reviewRevision = answer.revision;
      this.reviewCheckedLive = Boolean(this.ui("se-review-check-live").checked);
      this.reviewValid = (
        answer.errors === 0 && answer.changed_count > 0 &&
        (!this.reviewCheckedLive || answer.live_check?.matches === true)
      );
      this.ui("se-kit-download").disabled = !this.reviewValid;
      this.ui("se-kit-status").textContent = this.reviewValid
        ? (this.reviewCheckedLive
          ? "Kit can be created with a fresh remote-drift check."
          : "Offline export: remote baseline will be marked UNVERIFIED.")
        : "Fix validation errors or remote conflicts before downloading a kit.";
      reportElement.replaceChildren();
      const summary = document.createElement("p");
      summary.className = answer.errors || answer.live_check?.matches === false
        ? "se-review-danger" : "se-review-ok";
      summary.textContent = answer.changed_count + " changed files · " +
        answer.errors + " validation errors · " + answer.warnings + " warnings";
      reportElement.append(summary);
      const hash = document.createElement("p");
      hash.className = "se-review-hash";
      hash.textContent = "Draft SHA-256 " + answer.draft_sha256 +
        " · baseline SHA-256 " + answer.baseline_sha256;
      reportElement.append(hash);
      const live = document.createElement("p");
      const status = answer.live_check || {};
      live.textContent = status.checked
        ? status.matches
          ? "Remote drift: no conflicts in changed files (" +
            status.checked_files + " original files checked)."
          : "Remote drift: " + status.conflicts.length + " conflict(s) found."
        : "Remote drift check not performed (offline/local review).";
      live.className = status.checked
        ? status.matches ? "se-review-ok" : "se-review-danger"
        : "se-review-warning";
      reportElement.append(live);
      const files = document.createElement("div");
      files.className = "se-review-files";
      for (const item of answer.changed_files || []) {
        const row = document.createElement("div");
        row.className = "se-review-file";
        const title = document.createElement("strong");
        title.textContent = item.operation.toUpperCase() + " · " + item.path;
        const meta = document.createElement("small");
        meta.textContent = item.before_bytes + " → " + item.after_bytes +
          " bytes · SHA-256 " +
          (item.after_sha256 ? item.after_sha256.slice(0, 16) + "…" : "deleted");
        row.append(title, meta);
        files.append(row);
      }
      reportElement.append(files);
      for (const conflict of status.conflicts || []) {
        const note = document.createElement("p");
        note.className = "se-review-danger";
        note.textContent = "CONFLICT · " + conflict.path + ": " + conflict.reason;
        reportElement.append(note);
      }
      const blockers = document.createElement("div");
      blockers.className = "se-review-blockers";
      const heading = document.createElement("strong");
      heading.textContent = "Deployment remains unavailable";
      blockers.append(heading);
      for (const blocker of answer.blockers || []) {
        const item = document.createElement("p");
        item.textContent = blocker;
        blockers.append(item);
      }
      reportElement.append(blockers);
    } catch (error) {
      if (token !== this.reviewToken) return;
      reportElement.textContent =
        "Review failed: " + String(error.message || error) +
        ". The remote and stored draft were not modified.";
    } finally {
      // An edit can invalidate the request token before this finally block.
      // The initiating button must still be re-enabled.
      button.disabled = false;
    }
  }

  async downloadKit() {
    if (!this.draft || !this.entryId || !this.reviewValid || !this.reviewHash) {
      this.ui("se-kit-status").textContent =
        "Run a successful review before requesting the deployment kit.";
      return;
    }
    const isLive = this.ui("se-review-check-live").checked;
    if (isLive !== this.reviewCheckedLive) {
      this.clearReview("Review preference changed. Run review again.");
      return;
    }
    if (!isLive && !window.confirm(
      "Download an OFFLINE, UNVERIFIED deployment-review kit? The archive " +
      "will not claim that its baseline matches the current Waveshare. " +
      "It is not a flashable firmware image."
    )) return;
    const button = this.ui("se-kit-download");
    button.disabled = true;
    const entry = this.entryId;
    const expectedHash = this.reviewHash;
    const revision = this.reviewRevision;
    const status = this.ui("se-kit-status");
    status.textContent = "Building checked proposal and rollback archive…";
    try {
      const result = await this.studio.hass().callWS({
        type: "omote_manager/editor/export-kit",
        entry_id: entry,
        revision,
        draft_sha256: expectedHash,
        check_live: isLive
      });
      if (entry !== this.entryId || expectedHash !== this.reviewHash) {
        throw new Error("Remote or draft changed during download; review again.");
      }
      if (result.deployment_enabled !== false ||
          result.draft_sha256 !== expectedHash ||
          result.mime_type !== "application/zip" ||
          !result.base64) {
        throw new Error("Invalid or stale archive response from integration.");
      }
      const data = atob(result.base64);
      if (data.length !== result.bytes || data.length > 2 * 1024 * 1024) {
        throw new Error("Download failed archive size verification.");
      }
      const bytes = new Uint8Array(data.length);
      for (let i = 0; i < data.length; i++) bytes[i] = data.charCodeAt(i);
      const zip = new Blob([bytes], {type: "application/zip"});
      const url = URL.createObjectURL(zip);
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename || "omote-deployment-review-kit.zip";
      this.studio.root.append(link);
      link.click();
      link.remove();
      // Allow browser download manager to resolve the temporary blob.
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      status.textContent = "Review/rollback ZIP downloaded (" + result.bytes +
        " bytes, " + result.review_status + "). Remote was not modified.";
    } catch (error) {
      status.textContent = "Download failed: " + String(error.message || error) +
        ". Existing drafts and the remote remain unchanged.";
    } finally {
      button.disabled = !this.reviewValid;
    }
  }

  async revert() {
    if (!this.diffPath || !this.draft) return;
    const path = this.diffPath;
    if (!window.confirm(
      "Restore the original draft copy of " + path + "? " +
      "Changes in this Home Assistant draft file will be lost. " +
      "The physical OMOTE remote will not be modified."
    )) return;
    if (await this.change({
      type: "omote_manager/editor/revert", path
    }, "Draft file reverted.")) {
      this.note("Reverted local draft file " + path);
    }
  }
}

export function attachSceneEditor(studio) {
  return new SceneEditor(studio);
}
