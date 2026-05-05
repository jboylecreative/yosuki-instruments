/**
 * build_output_aep.jsx
 *
 * ExtendScript — run via: aerender -script build_output_aep.jsx
 *
 * Reads render_jobs.json from the data/ folder.
 * Opens the master template AEP, duplicates one composition per render job,
 * swaps all footage and text sources, then saves as the output AEP.
 *
 * Layer names expected in the master template compositions:
 *   BG_MEDIA       — footage layer (video background)
 *   TEXT_TAGLINE   — text layer
 *   TEXT_PRODUCT_NAME — text layer
 *   TEXT_CTA       — text layer
 *   LOGO           — footage layer
 */

// ── Paths injected by step_04_build_output_aep.py ─────────────────────────
// These vars are written into a companion file (aep_build_config.json)
// which this script reads at runtime.

var scriptDir = new File($.fileName).parent;
var rootDir = scriptDir.parent;
var configFile = new File(rootDir + "/data/aep_build_config.json");

if (!configFile.exists) {
    alert("aep_build_config.json not found. Run step 4 first.");
    $.quit(1);
}

configFile.open("r");
var configRaw = configFile.read();
configFile.close();
var cfg = JSON.parse(configRaw);

var masterPath = cfg.master_aep_path;
var outputPath = cfg.output_aep_path;
var jobs = cfg.jobs;

// ── Helper: find layer by name in a comp ─────────────────────────────────
function findLayer(comp, name) {
    for (var i = 1; i <= comp.layers.length; i++) {
        if (comp.layers[i].name === name) return comp.layers[i];
    }
    return null;
}

// ── Helper: apply or refresh drop shadow on a text layer ─────────────────
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
        return app.project.importFile(io);
    } catch (e) {
        $.writeln("ERROR importing " + filePath + ": " + e.message);
        return null;
    }
}

// ── Open master template ───────────────────────────────────────────────────
$.writeln("Opening master template: " + masterPath);
var masterFile = new File(masterPath);
if (!masterFile.exists) {
    alert("Master template not found: " + masterPath);
    $.quit(1);
}
app.open(masterFile);
var project = app.project;

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
        $.writeln("  WARNING: Composition not found: " + job.composition_name + " — skipping");
        continue;
    }

    // Duplicate the composition
    var newComp = srcComp.duplicate();
    newComp.name = job.comp_name;

    // Import bg video for this job
    var bgItem = importFile(job.bg_video_path);

    // Swap BG_MEDIA footage
    var bgLayer = findLayer(newComp, "BG_MEDIA");
    if (bgLayer && bgItem) {
        bgLayer.replaceSource(bgItem, false);
    }

    // Swap LOGO footage
    var logoLayer = findLayer(newComp, "LOGO");
    if (logoLayer && logoItem) {
        logoLayer.replaceSource(logoItem, false);
    }

    // Set text layers and ensure drop shadow on each
    var taglineLayer = findLayer(newComp, "TEXT_TAGLINE");
    if (taglineLayer) {
        taglineLayer.property("Source Text").setValue(job.tagline);
        ensureDropShadow(taglineLayer);
    }

    var productNameLayer = findLayer(newComp, "TEXT_PRODUCT_NAME");
    if (productNameLayer) {
        productNameLayer.property("Source Text").setValue(job.product_name);
        ensureDropShadow(productNameLayer);
    }

    var ctaLayer = findLayer(newComp, "TEXT_CTA");
    if (ctaLayer) {
        ctaLayer.property("Source Text").setValue(job.cta);
        ensureDropShadow(ctaLayer);
    }
}

// ── Save as output AEP ────────────────────────────────────────────────────
$.writeln("Saving output AEP: " + outputPath);
var outputFile = new File(outputPath);
app.project.save(outputFile);
$.writeln("Done. Output AEP saved.");
$.quit(0);
