/**
 * create_template.jsx
 *
 * ExtendScript — run inside After Effects to generate the master template from scratch.
 *
 * Creates 3 compositions with the required named layers:
 *   Billboard_970x250
 *   YouTube_1920x1080
 *   Instagram_1080x1080
 *
 * Layer structure per comp:
 *   BG_MEDIA           — AV layer (solid placeholder, blue tint)
 *   TEXT_TAGLINE       — text layer, left-aligned, drop shadow
 *   TEXT_PRODUCT_NAME  — text layer, left-aligned, drop shadow
 *   TEXT_CTA           — text layer, left-aligned, drop shadow
 *   LOGO               — solid placeholder (magenta tint)
 *
 * Text is positioned in the left area of the frame (right side reserved for the
 * instrument in the AI-generated background).
 *
 * After running: add keyframe animation to each comp, then save as
 *   templates/yosuki_master_template.aep
 *
 * Duration: 8 seconds at 30fps
 */

var DURATION = 8;
var FPS = 30;

var COMPS = [
    { name: "YouTube_1920x1080",   width: 1920, height: 1080 },
    { name: "Instagram_1080x1080", width: 1080, height: 1080 },
    { name: "Billboard_970x250",   width: 970,  height: 250  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function addSolidPlaceholder(comp, name, color, w, h, xPos, yPos) {
    var solid = comp.layers.addSolid(color, name, w, h, 1.0);
    solid.name = name;
    solid.inPoint = 0;
    solid.outPoint = DURATION;
    if (xPos !== undefined && yPos !== undefined) {
        solid.property("Position").setValue([xPos, yPos]);
    }
    return solid;
}

function addDropShadow(layer) {
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
        $.writeln("  Warning: could not add drop shadow to " + layer.name + ": " + e.message);
    }
}

function addTextLayer(comp, name, defaultText, xPos, yPos, fontSize) {
    var textLayer = comp.layers.addText(defaultText);
    textLayer.name = name;
    textLayer.inPoint = 0;
    textLayer.outPoint = DURATION;
    textLayer.property("Position").setValue([xPos, yPos]);

    var textDoc = textLayer.property("Source Text").value;
    textDoc.resetCharStyle();
    textDoc.fontSize = fontSize;
    textDoc.fillColor = [1, 1, 1];
    textDoc.justification = ParagraphJustification.LEFT_JUSTIFY;
    textLayer.property("Source Text").setValue(textDoc);

    addDropShadow(textLayer);
    return textLayer;
}

// ── Build comps ───────────────────────────────────────────────────────────────

app.newProject();
var project = app.project;

for (var c = 0; c < COMPS.length; c++) {
    var spec = COMPS[c];
    var w = spec.width;
    var h = spec.height;
    var isBillboard = (h <= 300);
    var isSquare = (w === h);

    var comp = project.items.addComp(spec.name, w, h, 1.0, DURATION, FPS);

    // BG_MEDIA — full-frame cyan placeholder at bottom of stack
    addSolidPlaceholder(comp, "BG_MEDIA", [0.1, 0.6, 0.8], w, h, w / 2, h / 2);

    // LOGO — magenta placeholder, bottom-center
    var logoW = Math.round(w * (isBillboard ? 0.06 : 0.10));
    var logoH = Math.round(h * (isBillboard ? 0.35 : 0.14));
    var logo = addSolidPlaceholder(comp, "LOGO", [0.9, 0.2, 0.6],
        logoW, logoH, w / 2, h * (isBillboard ? 0.65 : 0.84));

    // Text x-anchor: left margin based on size
    var leftX = isBillboard ? Math.round(w * 0.04) : Math.round(w * 0.07);

    if (isBillboard) {
        // Billboard: compact, single-line heights
        var taglineSize  = Math.round(h * 0.30);
        var productSize  = Math.round(h * 0.22);
        var ctaSize      = Math.round(h * 0.20);

        addTextLayer(comp, "TEXT_CTA",          "SHOP NOW",               leftX, h * 0.72, ctaSize);
        addTextLayer(comp, "TEXT_PRODUCT_NAME", "YOSUKI SIGNATURE SERIES",leftX, h * 0.52, productSize);
        addTextLayer(comp, "TEXT_TAGLINE",      "OWN THE STAGE",          leftX, h * 0.38, taglineSize);

    } else if (isSquare) {
        // 1:1 — text in upper-left
        var taglineSize  = Math.round(h * 0.075);
        var productSize  = Math.round(h * 0.048);
        var ctaSize      = Math.round(h * 0.042);

        addTextLayer(comp, "TEXT_CTA",          "SHOP NOW",               leftX, h * 0.76, ctaSize);
        addTextLayer(comp, "TEXT_PRODUCT_NAME", "YOSUKI SIGNATURE SERIES",leftX, h * 0.32, productSize);
        addTextLayer(comp, "TEXT_TAGLINE",      "OWN THE STAGE",          leftX, h * 0.22, taglineSize);

    } else {
        // 16:9 — text in left column, vertically centered
        var taglineSize  = Math.round(h * 0.080);
        var productSize  = Math.round(h * 0.048);
        var ctaSize      = Math.round(h * 0.042);

        addTextLayer(comp, "TEXT_CTA",          "SHOP NOW",               leftX, h * 0.78, ctaSize);
        addTextLayer(comp, "TEXT_PRODUCT_NAME", "YOSUKI SIGNATURE SERIES",leftX, h * 0.54, productSize);
        addTextLayer(comp, "TEXT_TAGLINE",      "OWN THE STAGE",          leftX, h * 0.42, taglineSize);
    }

    $.writeln("Created: " + spec.name);
}

$.writeln("\nTemplate created. Next steps:");
$.writeln("  1. Add keyframe animation to each composition.");
$.writeln("  2. Set Output Module to H.264 MP4.");
$.writeln("  3. Save as: templates/yosuki_master_template.aep");
