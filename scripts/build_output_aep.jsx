/**
 * build_output_aep.jsx
 *
 * Run headlessly via nexrender (called by step_04_build_output_aep.py).
 * When nexrender opens master_template.aep and runs this script as a prerender asset,
 * app.project is already the loaded master template — no app.open() needed.
 *
 * CONFIG_PATH is injected by step_04_build_output_aep.py before calling nexrender.
 * The script reads aep_build_config.json, duplicates one comp per render job,
 * swaps all footage and text sources, then saves as the output AEP.
 *
 * Layer names expected in the master template compositions:
 *   BG_MEDIA     — footage layer (video background); swapped per variant
 *   TEXT_TAGLINE — text layer (Century Gothic Bold, white); swapped per variant
 *   END_CARD     — white solid; NOT swapped — left as-is from template
 *   LOGO         — footage layer (centered on end card); swapped per variant
 *   TEXT_CTA     — text layer (Century Gothic Regular, dark); swapped per variant
 */

var CONFIG_PATH = "__CONFIG_PATH__";

// ── Custom-size derivation constants ─────────────────────────────────────────
// When a job requests a composition that doesn't exist in the master template
// (e.g. a custom size added via the dashboard), the script derives it by scaling
// YouTube_1920x1080 to the target canvas dimensions.
var HERO_COMP_NAME    = "YouTube_1920x1080";
var HERO_W            = 1920;
var HERO_H            = 1080;
var MIN_FONT_SIZE        = 16;   // px — floor applied after scaling text layers
var SAFE_MARGIN_PCT      = 0.04; // 4% inset — layer anchor must stay within this margin
var MIN_LOGO_CTA_GAP     = 20;   // px — minimum gap between LOGO bottom and TEXT_CTA top
var TAGLINE_BASELINE_LEN = 22;   // chars — EN taglines at or below this get no size reduction
var CTA_BASELINE_LEN     = 16;   // chars — EN CTAs at or below this get no size reduction
var TEXT_SCALE_FLOOR     = 0.62; // never shrink below 62% of the template font size (~German worst-case)

(function () {
    var configFile = new File(CONFIG_PATH);
    if (!configFile.exists) {
        $.writeln("ERROR: aep_build_config.json not found at: " + CONFIG_PATH);
        return;
    }

    configFile.open("r");
    var configRaw = configFile.read();
    configFile.close();
    var cfg = eval("(" + configRaw + ")");

    var outputPath = cfg.output_aep_path;
    var jobs = cfg.jobs;

    if (!outputPath) {
        $.writeln("ERROR: output_aep_path missing from config");
        return;
    }

    var project = app.project;

    // ── Snapshot existing items (these are the master template comps) ─────────
    var existingIds = {};
    for (var _i = 1; _i <= project.numItems; _i++) {
        existingIds[project.item(_i).id] = true;
    }

    // Maps newly created comp name → product_id / locale (for folder routing)
    var compProductMap = {};
    var compLocaleMap  = {};

    // ── Helper: convert "signature-series" → "Signature Series" ──────────────
    function toTitleCase(str) {
        var words = str.replace(/-/g, " ").split(" ");
        var out = "";
        for (var w = 0; w < words.length; w++) {
            if (words[w].length > 0) {
                out += (w > 0 ? " " : "") + words[w].charAt(0).toUpperCase() + words[w].slice(1);
            }
        }
        return out;
    }

    // ── Helper: find layer by name in a comp ──────────────────────────────────
    function findLayer(comp, name) {
        for (var i = 1; i <= comp.layers.length; i++) {
            if (comp.layers[i].name === name) return comp.layers[i];
        }
        return null;
    }

    // ── Helper: apply or refresh drop shadow on a text layer ──────────────────
    function ensureDropShadow(layer) {
        try {
            var ls = layer.property("ADBE Layer Styles");
            var ds = ls.property("ADBE Drop Shadow");
            ds.enabled = true;
            ds.property("ADBE DS Color").setValue([0, 0, 0, 1]);
            ds.property("ADBE DS Opacity").setValue(65);
            ds.property("ADBE DS Angle").setValue(135);
            ds.property("ADBE DS Distance").setValue(3);
            ds.property("ADBE DS Softness").setValue(12);
            ds.property("ADBE DS Spread").setValue(0);
        } catch (e) {
            $.writeln("  Warning: drop shadow on " + layer.name + ": " + e.message);
        }
    }

    // ── Helper: import a footage file ─────────────────────────────────────────
    function importFile(filePath) {
        var f = new File(filePath);
        if (!f.exists) {
            $.writeln("WARNING: File not found: " + filePath);
            return null;
        }
        var io = new ImportOptions(f);
        io.importAs = ImportAsType.FOOTAGE;
        try {
            return project.importFile(io);
        } catch (e) {
            $.writeln("ERROR importing " + filePath + ": " + e.message);
            return null;
        }
    }

    // ── Import cache — reuse same FootageItem for repeated source paths ────────
    // Prevents 5 identical imports (one per locale) for each background file.
    var importCache = {};
    function importFileCached(filePath) {
        if (importCache[filePath]) return importCache[filePath];
        var item = importFile(filePath);
        if (item) importCache[filePath] = item;
        return item;
    }

    // ── Custom-size derivation helpers ───────────────────────────────────────

    // Remap a single AE property's value (and all its keyframes) through mapFn.
    // Skips expression-driven properties to avoid breaking expressions.
    function _remapProp(prop, mapFn) {
        try {
            if (prop.expression && prop.expression !== "") return;
            if (prop.numKeys > 0) {
                for (var k = 1; k <= prop.numKeys; k++) {
                    try { prop.setValueAtKey(k, mapFn(prop.keyValue(k))); } catch (e) {}
                }
            } else {
                try { prop.setValue(mapFn(prop.value)); } catch (e) {}
            }
        } catch (e) {}
    }

    // Scale a layer's Position and Scale transform properties.
    // Position is remapped relative to the source and target canvas centres.
    function _scaleLayerTransform(layer, uScale, srcCX, srcCY, tgtCX, tgtCY) {
        _remapProp(layer.transform.position, function (v) {
            // v is [x, y] for 2D layers, [x, y, z] for 3D
            var nx = tgtCX + (v[0] - srcCX) * uScale;
            var ny = tgtCY + (v[1] - srcCY) * uScale;
            return (v.length > 2) ? [nx, ny, v[2] * uScale] : [nx, ny];
        });
        _remapProp(layer.transform.scale, function (v) {
            // Scale is [sx%, sy%] — multiply by uniform scale
            return (v.length > 2)
                ? [v[0] * uScale, v[1] * uScale, v[2]]
                : [v[0] * uScale, v[1] * uScale];
        });
    }

    // Scale font size on a text layer. Operates on all Source Text keyframes.
    function _scaleTextFontSize(layer, uScale) {
        try {
            var srcText = layer.property("Source Text");
            if (srcText.expression && srcText.expression !== "") return;
            if (srcText.numKeys > 0) {
                for (var k = 1; k <= srcText.numKeys; k++) {
                    try {
                        var doc = srcText.keyValue(k);
                        doc.fontSize = Math.max(Math.round(doc.fontSize * uScale), MIN_FONT_SIZE);
                        srcText.setValueAtKey(k, doc);
                    } catch (e) {}
                }
            } else {
                try {
                    var doc = srcText.value;
                    doc.fontSize = Math.max(Math.round(doc.fontSize * uScale), MIN_FONT_SIZE);
                    srcText.setValue(doc);
                } catch (e) {}
            }
        } catch (e) {
            $.writeln("  Warning: font scale on " + layer.name + ": " + e.message);
        }
    }

    // Shrink font size proportionally when text exceeds the English baseline length.
    // Keeps layout intact for longer locales (German, Japanese, etc.) without
    // touching the master template.
    function _autoScaleTextForLength(layer, text, baselineLen) {
        if (!text || text.length <= baselineLen) return;
        var scale = Math.max(baselineLen / text.length, TEXT_SCALE_FLOOR);
        _scaleTextFontSize(layer, scale);
    }

    // After scaling, enforce safe-area bounds and logo-CTA minimum gap.
    function _applyGuardrails(comp, tgtW, tgtH) {
        var marginX = Math.round(tgtW * SAFE_MARGIN_PCT);
        var marginY = Math.round(tgtH * SAFE_MARGIN_PCT);

        // ── Safe-area: keep every non-3D layer anchor within margin ─────────
        for (var li = 1; li <= comp.layers.length; li++) {
            var layer = comp.layers[li];
            if (layer.threeDLayer) continue;
            _remapProp(layer.transform.position, function (v) {
                return [
                    Math.min(Math.max(v[0], marginX), tgtW - marginX),
                    Math.min(Math.max(v[1], marginY), tgtH - marginY)
                ];
            });
        }

        // ── Logo-CTA gap: sample near the end-card phase ─────────────────────
        var logoLayer = null, ctaLayer = null;
        for (var li2 = 1; li2 <= comp.layers.length; li2++) {
            if (comp.layers[li2].name === "LOGO")     logoLayer = comp.layers[li2];
            if (comp.layers[li2].name === "TEXT_CTA") ctaLayer  = comp.layers[li2];
        }
        if (!logoLayer || !ctaLayer) return;

        try {
            var t = comp.duration * 0.85;
            var logoRect = logoLayer.sourceRectAtTime(t, false);
            var ctaRect  = ctaLayer.sourceRectAtTime(t, false);
            var logoPos  = logoLayer.transform.position.valueAtTime(t, false);
            var ctaPos   = ctaLayer.transform.position.valueAtTime(t, false);
            // logoRect.top is negative (above anchor); height is positive
            var logoBottom = logoPos[1] + (logoRect.top + logoRect.height);
            var ctaTop     = ctaPos[1]  + ctaRect.top;
            var gap = ctaTop - logoBottom;

            if (gap < MIN_LOGO_CTA_GAP) {
                var nudge = Math.ceil((MIN_LOGO_CTA_GAP - gap) / 2);
                _remapProp(logoLayer.transform.position, function (v) {
                    return [v[0], v[1] - nudge];
                });
                _remapProp(ctaLayer.transform.position, function (v) {
                    return [v[0], v[1] + nudge];
                });
                $.writeln("  Guardrail: LOGO/CTA gap — nudged each by " + nudge + "px");
            }
        } catch (e) {
            $.writeln("  Warning: logo-CTA gap check: " + e.message);
        }
    }

    // Derive a new comp from the hero (YouTube_1920x1080) for a custom canvas size.
    // Returns the derived CompItem, or null on failure.
    // derivedCompCache ensures each custom size is only derived once.
    var derivedCompCache = {};

    function deriveCompFromHero(heroComp, tgtW, tgtH, baseName) {
        if (derivedCompCache[baseName]) return derivedCompCache[baseName];

        $.writeln("  Deriving comp '" + baseName + "' from " + HERO_COMP_NAME +
                  " (" + HERO_W + "x" + HERO_H + " → " + tgtW + "x" + tgtH + ")");

        var uScale = Math.min(tgtW / HERO_W, tgtH / HERO_H);
        var srcCX  = HERO_W / 2;
        var srcCY  = HERO_H / 2;
        var tgtCX  = tgtW / 2;
        var tgtCY  = tgtH / 2;

        var derived = heroComp.duplicate();
        derived.name = baseName + "__derived_base";
        derived.width  = tgtW;
        derived.height = tgtH;

        for (var li = 1; li <= derived.layers.length; li++) {
            var layer = derived.layers[li];

            // BG_MEDIA fills the canvas — reset to centre at 100% rather than scaling
            if (layer.name === "BG_MEDIA") {
                _remapProp(layer.transform.position, function () { return [tgtCX, tgtCY]; });
                _remapProp(layer.transform.scale,    function () { return [100, 100]; });
                continue;
            }

            // END_CARD solid — stretch to fill new canvas
            if (layer.name === "END_CARD") {
                try {
                    var sw = layer.source.width  || HERO_W;
                    var sh = layer.source.height || HERO_H;
                    _remapProp(layer.transform.position, function () { return [tgtCX, tgtCY]; });
                    _remapProp(layer.transform.scale, function () {
                        return [(tgtW / sw) * 100, (tgtH / sh) * 100];
                    });
                } catch (e) {}
                continue;
            }

            // All other layers — scale transforms
            _scaleLayerTransform(layer, uScale, srcCX, srcCY, tgtCX, tgtCY);
            if (layer instanceof TextLayer) {
                _scaleTextFontSize(layer, uScale);
            }
        }

        _applyGuardrails(derived, tgtW, tgtH);

        derivedCompCache[baseName] = derived;
        return derived;
    }

    // ── Pre-import the logo (shared across all comps) ─────────────────────────
    var logoItem = null;
    if (cfg.logo_path) {
        logoItem = importFile(cfg.logo_path);
    }

    // ── Process each job ──────────────────────────────────────────────────────
    $.writeln("Processing " + jobs.length + " render jobs...");

    for (var j = 0; j < jobs.length; j++) {
        var job = jobs[j];
        $.writeln("[" + (j + 1) + "/" + jobs.length + "] " + job.output_filename);

        // Find the source composition (by composition_name)
        var srcComp = null;
        for (var i = 1; i <= project.numItems; i++) {
            var item = project.item(i);
            if (item instanceof CompItem && item.name === job.composition_name) {
                srcComp = item;
                break;
            }
        }
        if (!srcComp) {
            // Composition not in master template — derive it from the hero 16:9 comp
            var heroComp = null;
            for (var hi = 1; hi <= project.numItems; hi++) {
                var hItem = project.item(hi);
                if (hItem instanceof CompItem && hItem.name === HERO_COMP_NAME) {
                    heroComp = hItem;
                    break;
                }
            }
            if (!heroComp) {
                $.writeln("  ERROR: '" + job.composition_name + "' not found and hero comp '" +
                          HERO_COMP_NAME + "' is missing — skipping");
                continue;
            }
            var tgtW = job.width  || HERO_W;
            var tgtH = job.height || HERO_H;
            srcComp = deriveCompFromHero(heroComp, tgtW, tgtH, job.composition_name);
            if (!srcComp) {
                $.writeln("  ERROR: Failed to derive comp for " + job.composition_name + " — skipping");
                continue;
            }
            // Register derived base comp as a template item so it goes into Templates/ folder
            existingIds[srcComp.id] = true;
        }

        // Duplicate the composition and register it for folder placement
        var newComp = srcComp.duplicate();
        newComp.name = job.comp_name;
        compProductMap[job.comp_name] = job.product_id;
        compLocaleMap[job.comp_name]  = job.locale.toUpperCase();

        // Import background media (Stage 1 still PNG) — cached so locale siblings share one FootageItem
        var bgItem = importFileCached(job.bg_media_path);

        // Swap BG_MEDIA footage
        var bgLayer = findLayer(newComp, "BG_MEDIA");
        if (bgLayer && bgItem) {
            bgLayer.replaceSource(bgItem, false);
            // If the background is a still image, stretch it to fill the full comp duration
            if (bgItem.mainSource instanceof SolidSource === false &&
                bgItem.mainSource.isStill) {
                bgLayer.outPoint = newComp.duration;
            }
        }

        // Swap LOGO footage
        var logoLayer = findLayer(newComp, "LOGO");
        if (logoLayer && logoItem) {
            logoLayer.replaceSource(logoItem, false);
        }

        // Set text layers
        var taglineLayer = findLayer(newComp, "TEXT_TAGLINE");
        if (taglineLayer) {
            taglineLayer.property("Source Text").setValue(job.tagline);
            ensureDropShadow(taglineLayer);
            _autoScaleTextForLength(taglineLayer, job.tagline, TAGLINE_BASELINE_LEN);
        }

        var ctaLayer = findLayer(newComp, "TEXT_CTA");
        if (ctaLayer) {
            ctaLayer.property("Source Text").setValue(job.cta);
            ensureDropShadow(ctaLayer);
            _autoScaleTextForLength(ctaLayer, job.cta, CTA_BASELINE_LEN);
        }

        // Add comp to the render queue with a lossless output path.
        // Step 5 calls aerender once on this AEP — it processes the full queue,
        // then Python/FFmpeg batch-encodes the lossless files to H.264 MP4.
        if (job.output_lossless_path) {
            try {
                var rqi = app.project.renderQueue.items.add(newComp);
                rqi.outputModule(1).applyTemplate("Lossless");
                rqi.outputModule(1).file = new File(job.output_lossless_path);
            } catch (e) {
                $.writeln("  Warning: render queue add failed for " + newComp.name + ": " + e.message);
            }
        }
    }

    // ── Organise project panel into folders ───────────────────────────────────
    // Structure:
    //   Templates/          ← original master template comps
    //   Outputs/
    //     Signature Series/
    //       EN/             ← one locale subfolder per instrument
    //       JA/
    //     Savant Series/
    //       EN/
    //   Assets/             ← all imported footage (BG stills/videos, logo)

    var templatesFolder = project.items.addFolder("Templates");
    var outputsFolder   = project.items.addFolder("Outputs");
    var assetsFolder    = project.items.addFolder("Assets");

    // Collect a snapshot of ALL items now (before moves shift indices)
    var allItems = [];
    for (var _j = 1; _j <= project.numItems; _j++) {
        allItems.push(project.item(_j));
    }

    var instrumentFolders = {}; // product_id → FolderItem
    var localeFolders     = {}; // product_id + "_" + locale → FolderItem

    for (var _k = 0; _k < allItems.length; _k++) {
        var _item = allItems[_k];

        // Skip the three folders we just created
        if (_item === templatesFolder || _item === outputsFolder || _item === assetsFolder) continue;

        if (existingIds[_item.id]) {
            // Pre-existing item = master template comp
            if (_item instanceof CompItem) {
                _item.parentFolder = templatesFolder;
            }
        } else if (_item instanceof CompItem) {
            // Newly created output comp — route into Outputs/<instrument>/<locale>/
            var _pid    = compProductMap[_item.name];
            var _locale = compLocaleMap[_item.name];
            if (_pid) {
                // Instrument folder
                if (!instrumentFolders[_pid]) {
                    var _instrF = project.items.addFolder(toTitleCase(_pid));
                    _instrF.parentFolder = outputsFolder;
                    instrumentFolders[_pid] = _instrF;
                }
                // Locale subfolder within instrument folder
                var _localeKey = _pid + "_" + _locale;
                if (_locale && !localeFolders[_localeKey]) {
                    var _locF = project.items.addFolder(_locale);
                    _locF.parentFolder = instrumentFolders[_pid];
                    localeFolders[_localeKey] = _locF;
                }
                _item.parentFolder = _locale ? localeFolders[_localeKey] : instrumentFolders[_pid];
            } else {
                _item.parentFolder = outputsFolder;
            }
        } else if (_item instanceof FootageItem) {
            // All imported footage goes to Assets
            _item.parentFolder = assetsFolder;
        }
    }

    // ── Collect Files: copy all linked footage into (Footage)/ subfolder ─────
    // Mirrors After Effects "File > Collect Files" — makes the package self-contained.
    var outputFile = new File(outputPath);
    var runFolder  = outputFile.parent;
    if (!runFolder.exists) { runFolder.create(); }

    var footageDir = new Folder(runFolder.fsName + "/(Footage)");
    if (!footageDir.exists) { footageDir.create(); }

    var usedNames = {};
    var collected = 0;

    for (var ci = 1; ci <= project.numItems; ci++) {
        var cItem = project.item(ci);
        if (!(cItem instanceof FootageItem) || !cItem.file) continue; // skip solids/nulls

        var src     = cItem.file;
        var base    = src.name.replace(/\.[^.]+$/, "");
        var extM    = src.name.match(/\.[^.]+$/);
        var ext     = extM ? extM[0] : "";
        var dName   = src.name;
        var counter = 1;
        while (usedNames[dName]) { dName = base + "_" + counter++ + ext; }
        usedNames[dName] = true;

        var destFile = new File(footageDir.fsName + "/" + dName);
        if (src.copy(destFile.fsName)) {
            cItem.replace(destFile);
            collected++;
        } else {
            $.writeln("  WARNING: Could not copy " + src.fsName);
        }
    }

    // ── Save output AEP (paths now point to local (Footage)/ copies) ─────────
    $.writeln("Saving output AEP: " + outputPath);
    project.save(outputFile);
    $.writeln("Done. Collected " + collected + " footage files. Output AEP saved.");

}());
