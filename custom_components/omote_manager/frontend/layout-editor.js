/* OMOTE visual layout editor. Browser-only preview; all saved edits go to HA
 * WorkspaceStore using the existing administrator-only WebSocket API.
 * No remote command is sent and no firmware files are written.
 */
class VisualLayoutEditor {
  constructor(sceneEditor) {
    this.editor = sceneEditor;
    this.studio = sceneEditor.studio;
    this.selected = 0;
    this.pending = false;
    this.dragging = null;
    this.build();
    this.render();
  }

  ui(id) { return this.root.querySelector("#" + id); }
  get page() { return this.editor.page; }
  get widget() { return this.page?.widgets?.find(w => w.index === this.selected); }

  build() {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = "/omote_manager_static/layout-editor.css?v=0.1.0-dev8";
    this.studio.root.append(stylesheet);
    const section = document.createElement("section");
    section.className = "layout-editor";
    section.innerHTML = [
      '<header class="lp-header"><div><h4>5. Visual page layout</h4>',
      '<p class="muted">Waveshare ESP32-S3 LCD 2.8 V2 · 240 × 320 px (portrait)</p>',
      '</div><span class="lp-preview-badge">APPROXIMATE PREVIEW</span></header>',
      '<p class="lp-guidance">Select a widget to inspect its actual JSON layout fields. ',
      'Drag movable widgets on the preview to propose new percentage coordinates, ',
      'then choose <strong>Save layout to draft</strong>. Positioning and sizes ',
      'are approximations of LVGL behavior, not a pixel-exact device simulator.</p>',
      '<p id="lp-alert" class="lp-alert" role="status" aria-live="polite"></p>',
      '<div class="lp-columns">',
      '  <div class="lp-device">',
      '    <div class="lp-device-frame">',
      '      <div class="lp-display">',
      '        <div class="lp-status"><span id="lp-scene-name">OMOTE</span><span>●</span></div>',
      '        <div class="lp-body" id="lp-body"></div>',
      '        <div class="lp-tabbar" id="lp-tabbar">Page</div>',
      '      </div>',
      '    </div>',
      '    <p class="muted lp-scale-caption">Schematic 240 × 320 canvas; tab/status areas are estimates.</p>',
      '  </div>',
      '  <div class="lp-inspector">',
      '    <form id="lp-form">',
      '      <h4>Widget layout properties</h4>',
      '      <label>Widget<select name="widget"></select></label>',
      '      <div id="lp-widget-info" class="lp-widget-info"></div>',
      '      <label>Position mode<select name="mode">',
      '        <option value="flow">Automatic flow (no explicit position)</option>',
      '        <option value="align">Align relative to earlier widget</option>',
      '        <option value="absolute">Explicit position (percent)</option>',
      '      </select></label>',
      '      <label id="lp-align-wrap">AlignTo<select name="align_to"></select></label>',
      '      <div class="lp-field-row">',
      '        <label id="lp-x-wrap">PosX (%)<input name="x_pct" type="number" min="0" max="100" step="1" required></label>',
      '        <label id="lp-y-wrap">PosY (%)<input name="y_pct" type="number" min="0" max="100" step="1" required></label>',
      '      </div>',
      '      <div class="lp-field-row">',
      '        <label>Width (%)<input name="width_pct" type="number" min="1" max="100" step="1" placeholder="Default"></label>',
      '        <label>Height (%)<input name="height_pct" type="number" min="1" max="100" step="1" placeholder="Default"></label>',
      '      </div>',
      '      <p id="lp-size-help" class="muted lp-size-help"></p>',
      '      <button type="submit" id="lp-save">Save layout to draft</button>',
      '      <p class="lp-dirty" id="lp-dirty">No pending layout changes.</p>',
      '    </form>',
      '  </div>',
      '</div>',
      '<p class="lp-shared">A page file can be referenced by several scenes. Changes ',
      'to this page layout will affect every scene that uses the same JSON file. ',
      'Use the original-versus-draft comparison below to review edits.</p>'
    ].join("");
    const diff = this.editor.ui("se-diff").closest(".se-diff");
    diff.parentNode.insertBefore(section, diff);
    this.root = section;
    const form = this.ui("lp-form");
    form.elements.widget.addEventListener("change", e => {
      this.selected = Number(e.target.value);
      this.pending = false;
      this.renderInspector();
      this.renderPreview();
      this.editor.widgetIndex = this.selected;
    });
    form.elements.mode.addEventListener("change", () => {
      this.pending = true;
      this.syncControls();
      this.renderPreview();
    });
    for (const name of ["align_to", "x_pct", "y_pct", "width_pct", "height_pct"]) {
      form.elements[name].addEventListener("input", () => {
        this.pending = true;
        this.ui("lp-dirty").textContent = "Unsaved changes. Select Save layout to draft.";
        this.renderPreview();
      });
    }
    form.addEventListener("submit", e => {
      e.preventDefault();
      void this.save();
    });
  }

  select(element, values, current) {
    element.replaceChildren();
    for (const [value, label] of values) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = String(label);
      element.append(option);
    }
    if (values.some(([value]) => String(value) === String(current))) {
      element.value = String(current);
    }
  }

  note(text, error = false) {
    const element = this.ui("lp-alert");
    element.textContent = text;
    element.classList.toggle("error", error);
  }

  onRemoteChanged() {
    this.selected = 0;
    this.pending = false;
    this.dragging = null;
    this.render();
  }

  render() {
    this.ui("lp-scene-name").textContent = this.editor.detail?.screen_name || "OMOTE";
    this.ui("lp-tabbar").textContent = this.page?.short_name || this.page?.name || "Page";
    const items = (this.page?.widgets || []).filter(w => w.layout?.supported);
    if (!items.some(w => w.index === this.selected)) {
      this.selected = items[0]?.index ?? 0;
    }
    this.select(this.ui("lp-form").elements.widget, items.map(w => [
      w.index, "#" + (w.index + 1) + " · " + w.type +
        (w.text ? " · " + w.text : "")
    ]), this.selected);
    this.renderInspector();
    this.renderPreview();
  }

  renderInspector() {
    const widget = this.widget;
    const form = this.ui("lp-form");
    for (const field of form.querySelectorAll("input, select, button")) {
      field.disabled = !widget;
    }
    if (!widget) {
      this.ui("lp-widget-info").textContent = "Select a page with supported layout widgets.";
      this.ui("lp-size-help").textContent = "";
      return;
    }
    const layout = widget.layout;
    form.elements.mode.value = layout.mode;
    form.elements.mode.querySelector('option[value="absolute"]').disabled =
      !layout.can_position;
    this.select(form.elements.align_to, [
      [0, "0 · top of page"],
      ...this.page.widgets.filter(w => w.index < widget.index).map(w => [
        w.index + 1, (w.index + 1) + " · below " + w.type
      ]),
    ], layout.align_to);
    form.elements.x_pct.value = Number.isInteger(layout.x_pct) ? layout.x_pct : 0;
    form.elements.y_pct.value = Number.isInteger(layout.y_pct) ? layout.y_pct : 0;
    form.elements.width_pct.value = layout.width_pct ?? "";
    form.elements.height_pct.value = layout.height_pct ?? "";
    form.elements.width_pct.disabled = !layout.can_size_pct;
    form.elements.height_pct.disabled = !layout.can_height_pct;
    this.ui("lp-widget-info").textContent = widget.type + " · " +
      (widget.command == null ? "No command" :
        Array.isArray(widget.command) ? widget.command.join(", ") : widget.command);
    this.ui("lp-size-help").textContent =
      widget.type === "Image"
        ? "Image uses SizeXYinPixels; image dimensions are not edited in this version."
        : layout.can_size_pct
          ? "OMOTE SizeXY is percentage-based, not pixels. Empty size fields keep firmware defaults."
          : "This widget type does not support percentage width.";
    this.pending = false;
    this.ui("lp-dirty").textContent = "No pending layout changes.";
    this.syncControls();
  }

  syncControls() {
    const form = this.ui("lp-form");
    const mode = form.elements.mode.value;
    this.ui("lp-align-wrap").hidden = mode !== "align";
    this.ui("lp-x-wrap").hidden = mode !== "absolute";
    this.ui("lp-y-wrap").hidden = mode !== "absolute";
    this.ui("lp-dirty").textContent = this.pending
      ? "Unsaved changes. Select Save layout to draft."
      : "No pending layout changes.";
  }

  currentSettings() {
    const form = this.ui("lp-form").elements;
    const optional = input => input.value.trim() === "" ? null : Number(input.value);
    return {
      mode: form.mode.value,
      align_to: Number(form.align_to.value || 0),
      x_pct: Number(form.x_pct.value || 0),
      y_pct: Number(form.y_pct.value || 0),
      width_pct: optional(form.width_pct),
      height_pct: optional(form.height_pct)
    };
  }

  approximate(widget) {
    const layout = widget.index === this.selected && this.pending
      ? {...widget.layout, ...this.currentSettings()} : widget.layout;
    const kind = widget.type;
    const fallback = {
      Title: 8, Label: 8, Button: 12, ColorButtons: 14,
      NumberPad: 32, HaToggle: 12, HaLabel: 8, HaSwitch: 12,
      HaSlider: 10, HaMomentary: 12, HaClimate: 35, Image: 15
    };
    const height = Number(layout?.height_pct || fallback[kind] || 10);
    const width = Number(layout?.width_pct || (kind === "Image" ? 70 : 90));
    return {
      layout, height: Math.min(100, Math.max(5, height)),
      width: Math.min(100, Math.max(5, width))
    };
  }

  renderPreview() {
    const body = this.ui("lp-body");
    body.replaceChildren();
    const widgets = this.page?.widgets || [];
    const rects = new Map();
    let lastBottom = 2;
    const gap = 3;
    for (const widget of widgets) {
      const {layout, width, height} = this.approximate(widget);
      let x = Math.max(0, (100 - width) / 2);
      let y = lastBottom;
      if (layout?.mode === "absolute") {
        x = Number(layout.x_pct) || 0;
        y = Number(layout.y_pct) || 0;
      } else if (layout?.mode === "align") {
        const anchor = (Number(layout.align_to) || 0) - 1;
        const previous = rects.get(anchor);
        y = previous ? previous.bottom + gap : 2;
      }
      const item = document.createElement("button");
      item.type = "button";
      item.className = "lp-widget" +
        (widget.index === this.selected ? " selected" : "") +
        (layout?.supported ? " editable" : " readonly");
      item.style.left = x + "%";
      item.style.top = y + "%";
      item.style.width = width + "%";
      item.style.height = height + "%";
      item.dataset.widget = String(widget.index);
      const primary = document.createElement("span");
      primary.textContent = widget.text || widget.type || "Widget";
      const secondary = document.createElement("small");
      secondary.textContent = "#" + (widget.index + 1) + " · " + widget.type;
      item.append(primary, secondary);
      item.title = "Widget #" + (widget.index + 1) + " · " +
        (layout?.supported ? "click to inspect; drag if supported" : "read-only");
      item.addEventListener("click", () => this.choose(widget.index));
      if (layout?.supported && layout.can_position) {
        item.addEventListener("pointerdown", e => this.startDrag(e, item, widget.index));
        item.addEventListener("pointermove", e => this.moveDrag(e, item));
        item.addEventListener("pointerup", e => this.endDrag(e, item));
        item.addEventListener("pointercancel", e => this.endDrag(e, item));
      }
      rects.set(widget.index, {bottom: y + height});
      lastBottom = Math.max(lastBottom, y + height + gap);
      body.append(item);
    }
    if (!widgets.length) {
      const empty = document.createElement("p");
      empty.className = "lp-preview-empty";
      empty.textContent = "No widgets in the selected page";
      body.append(empty);
    }
  }

  choose(index) {
    if (index === this.selected) return;
    this.selected = index;
    this.pending = false;
    this.editor.widgetIndex = index;
    this.select(this.ui("lp-form").elements.widget,
      this.page.widgets.filter(w => w.layout?.supported).map(w => [
        w.index, "#" + (w.index + 1) + " · " + w.type
      ]), index);
    this.renderInspector();
    this.renderPreview();
  }

  startDrag(event, element, index) {
    if (event.button !== 0) return;
    if (this.selected !== index) {
      this.selected = index;
      this.editor.widgetIndex = index;
      this.renderInspector();
      this.ui("lp-form").elements.widget.value = String(index);
    }
    const r = element.getBoundingClientRect();
    this.dragging = {
      index, id: event.pointerId,
      offsetX: event.clientX - r.left,
      offsetY: event.clientY - r.top
    };
    element.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  moveDrag(event, element) {
    if (!this.dragging || this.dragging.id !== event.pointerId ||
        this.dragging.index !== Number(element.dataset.widget)) return;
    const rect = this.ui("lp-body").getBoundingClientRect();
    const x = Math.max(0, Math.min(100, Math.round(
      (event.clientX - rect.left - this.dragging.offsetX) * 100 / rect.width
    )));
    const y = Math.max(0, Math.min(100, Math.round(
      (event.clientY - rect.top - this.dragging.offsetY) * 100 / rect.height
    )));
    const form = this.ui("lp-form").elements;
    form.mode.value = "absolute";
    form.x_pct.value = x;
    form.y_pct.value = y;
    this.pending = true;
    this.syncControls();
    element.style.left = x + "%";
    element.style.top = y + "%";
  }

  endDrag(event, element) {
    if (!this.dragging || this.dragging.id !== event.pointerId) return;
    this.dragging = null;
    if (element.hasPointerCapture(event.pointerId)) {
      element.releasePointerCapture(event.pointerId);
    }
    this.ui("lp-dirty").textContent = this.pending
      ? "Position changed locally. Click Save layout to draft."
      : "No pending layout changes.";
  }

  async save() {
    const widget = this.widget;
    if (!widget || !widget.layout?.supported || !this.editor.entryId) return;
    const settings = this.currentSettings();
    const success = await this.editor.change({
      type: "omote_manager/editor/edit-layout",
      scene_path: this.editor.scenePath,
      page_index: this.editor.pageIndex,
      widget_index: this.selected,
      settings
    }, "Layout saved to Home Assistant draft.");
    if (success) {
      this.pending = false;
      this.note("Widget layout saved in Home Assistant draft. Validate and inspect the file diff.");
    } else {
      this.note("Layout was not saved. Review the message in Profile Studio.", true);
    }
  }
}

export function attachVisualLayoutEditor(sceneEditor) {
  return new VisualLayoutEditor(sceneEditor);
}
