/**
 * create_template.jsx
 *
 * ExtendScript — run inside After Effects once to generate the master template.
 * File > Scripts > Run Script File → select this file.
 *
 * Creates 3 fully-animated compositions:
 *   YouTube_1920x1080
 *   Instagram_1080x1080
 *   Billboard_970x250
 *
 * Layer stack per comp (back → front):
 *   BG_MEDIA   — solid placeholder; swapped with AI-generated image/video at render time
 *   TEXT_TAGLINE — Century Gothic Bold, white, drop shadow; animates over the BG
 *   END_CARD   — white solid; wipes in from the right to reveal the end card
 *   LOGO       — solid placeholder; centered on end card; swapped with real logo at render time
 *   TEXT_CTA   — Century Gothic Regular, dark; centered below logo on end card
 *
 * Timing — identical for all 3 sizes:
 *   0.0 – 2.0s  BG plays alone (Ken Burns push-in throughout)
 *   2.0 – 2.3s  TEXT_TAGLINE fades in + slides up 20px
 *   2.3 – 4.7s  TEXT_TAGLINE holds
 *   4.7 – 5.0s  TEXT_TAGLINE fades out
 *   5.0 – 5.5s  END_CARD white solid wipes in from the right
 *   5.4 – 5.7s  LOGO fades in (overlaps tail of wipe)
 *   5.5 – 5.8s  TEXT_CTA fades in
 *   5.8 – 8.0s  End card holds
 *
 * Saves automatically to: templates/master_template.aep
 */

var DURATION = 8;
var FPS      = 30;

var COMPS = [
    { name: "YouTube_1920x1080",   width: 1920, height: 1080 },
    { name: "Instagram_1080x1080", width: 1080, height: 1080 },
    { name: "Billboard_970x250",   width: 970,  height: 250  },
];

// Timing (seconds) — shared across all comp sizes
var T_TAGLINE_IN      = 2.0;
var T_TAGLINE_IN_END  = 2.3;
var T_TAGLINE_OUT     = 4.7;
var T_TAGLINE_OUT_END = 5.0;
var T_CARD_IN         = 5.0;
var T_CARD_IN_END     = 5.5;
var T_LOGO_IN         = 5.4;
var T_LOGO_IN_END     = 5.7;
var T_CTA_IN          = 5.5;
var T_CTA_IN_END      = 5.8;

// ── Ease helpers ──────────────────────────────────────────────────────────────

/**
 * Returns a KeyframeEase array whose length matches the property's dimension.
 * Required because AE reports Scale as 3D internally even for 2D comps.
 */
function easeArrayFor(prop, hardness) {
    hardness = hardness || 33;
    var val  = prop.value;
    var dims = (val instanceof Array) ? val.length : 1;
    var arr  = [];
    for (var d = 0; d < dims; d++) arr.push(new KeyframeEase(0, hardness));
    return arr;
}

/** Apply easy-ease to every keyframe on a property. */
function easeAllKeys(prop, hardness) {
    var ease = easeArrayFor(prop, hardness || 33);
    for (var k = 1; k <= prop.numKeys; k++) {
        try {
            prop.setTemporalEaseAtKey(k, ease, ease);
        } catch (e) {
            $.writeln("  Ease skipped key " + k + " on " + prop.name + ": " + e.message);
        }
    }
}

// ── Animation helpers ─────────────────────────────────────────────────────────

function animOpacity(layer, keyPairs) {
    var prop = layer.property("Opacity");
    for (var i = 0; i < keyPairs.length; i++) {
        prop.setValueAtTime(keyPairs[i][0], keyPairs[i][1]);
    }
    easeAllKeys(prop, 33);
}

function animScale(layer, startPct, duration) {
    var prop = layer.property("Scale");
    var val  = prop.value;
    var s0   = (val instanceof Array) ? [] : startPct;
    var s1   = (val instanceof Array) ? [] : 100;
    if (val instanceof Array) {
        for (var d = 0; d < val.length; d++) { s0.push(startPct); s1.push(100); }
    }
    prop.setValueAtTime(0,        s0);
    prop.setValueAtTime(duration, s1);
    easeAllKeys(prop, 50);
}

/** Animate a position property from posStart to posEnd between t0 and t1. */
function animPosition(layer, posStart, posEnd, t0, t1) {
    var prop = layer.property("Position");
    prop.setValueAtTime(t0, posStart);
    prop.setValueAtTime(t1, posEnd);
    easeAllKeys(prop, 50);
}

// ── Layer creation helpers ────────────────────────────────────────────────────

function addDropShadow(layer) {
    try {
        var ds = layer.property("ADBE Layer Styles").property("ADBE Drop Shadow");
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

/**
 * Add a text layer.
 * justify: ParagraphJustification constant (LEFT_JUSTIFY or CENTER_JUSTIFY)
 * color:   [r, g, b] 0–1 float
 * shadow:  true/false
 */
function makeText(comp, name, text, font, xPos, yPos, fontSize, justify, color, shadow) {
    var layer = comp.layers.addText(text);
    layer.name     = name;
    layer.inPoint  = 0;
    layer.outPoint = DURATION;
    layer.property("Position").setValue([xPos, yPos]);

    var doc = layer.property("Source Text").value;
    doc.resetCharStyle();
    doc.font          = font;
    doc.fontSize      = fontSize;
    doc.fillColor     = color || [1, 1, 1];
    doc.justification = justify || ParagraphJustification.LEFT_JUSTIFY;
    layer.property("Source Text").setValue(doc);

    if (shadow) addDropShadow(layer);
    return layer;
}

/** Add a solid-color placeholder layer with anchor at its center. */
function makeSolid(comp, name, color, w, h, xPos, yPos) {
    var layer = comp.layers.addSolid(color, name, w, h, 1.0);
    layer.name     = name;
    layer.inPoint  = 0;
    layer.outPoint = DURATION;
    layer.property("Anchor Point").setValue([w / 2, h / 2]);
    layer.property("Position").setValue([xPos, yPos]);
    return layer;
}

// ── Build comps ───────────────────────────────────────────────────────────────

app.newProject();
var project = app.project;

for (var c = 0; c < COMPS.length; c++) {
    var spec = COMPS[c];
    var w    = spec.width;
    var h    = spec.height;
    var isBillboard = (h <= 300);
    var isSquare    = (!isBillboard && w === h);

    var comp = project.items.addComp(spec.name, w, h, 1.0, DURATION, FPS);

    // ── Size-specific metrics ─────────────────────────────────────────────────

    var leftX = isBillboard ? Math.round(w * 0.04) : Math.round(w * 0.07);

    // Tagline — left-aligned, appears over BG
    var taglineSize, taglineY;
    // End-card LOGO — centered
    var logoW, logoH, logoY;
    // End-card CTA — centered below logo
    var ctaSize, ctaY;

    if (isBillboard) {
        taglineSize = Math.round(h * 0.24);   // 80% of original 0.30
        taglineY    = Math.round(h * 0.52);
        logoW       = Math.round(h * 0.098);  // ~10% of h — small badge on end card
        logoH       = Math.round(h * 0.091);
        logoY       = Math.round(h * 0.38);
        ctaSize     = Math.round(h * 0.18);
        ctaY        = Math.round(h * 0.78);

    } else if (isSquare) {
        taglineSize = Math.round(h * 0.078);
        taglineY    = Math.round(h * 0.46);
        logoW       = Math.round(w * 0.18);   // reduced from 0.30
        logoH       = Math.round(h * 0.12);   // reduced from 0.20
        logoY       = Math.round(h * 0.38);
        ctaSize     = Math.round(h * 0.040);
        ctaY        = Math.round(h * 0.65);

    } else {
        // 16:9
        taglineSize = Math.round(h * 0.082);
        taglineY    = Math.round(h * 0.46);
        logoW       = Math.round(w * 0.13);   // reduced from 0.22
        logoH       = Math.round(h * 0.13);   // reduced from 0.22
        logoY       = Math.round(h * 0.38);
        ctaSize     = Math.round(h * 0.040);
        ctaY        = Math.round(h * 0.65);
    }

    // ── Create layers — added back-to-front so last added = frontmost ─────────

    // 1. BG_MEDIA (back)
    var bgLayer = makeSolid(comp, "BG_MEDIA", [0.12, 0.55, 0.75], w, h, w / 2, h / 2);
    animScale(bgLayer, 108, DURATION);

    // 2. TEXT_TAGLINE — white, left-aligned, drop shadow; sits above BG
    var taglineLayer = makeText(
        comp, "TEXT_TAGLINE", "OWN THE STAGE",
        "CenturyGothic-Bold",
        leftX, taglineY, taglineSize,
        ParagraphJustification.LEFT_JUSTIFY, [1, 1, 1], true
    );

    // 3. END_CARD — white solid; starts off-frame right, wipes left to cover all
    //    inPoint = T_CARD_IN so the layer simply doesn't exist before the wipe starts
    var cardLayer = makeSolid(comp, "END_CARD", [1, 1, 1], w, h, w * 1.5, h / 2);
    cardLayer.inPoint = T_CARD_IN;
    animPosition(cardLayer, [w * 1.5, h / 2], [w / 2, h / 2], T_CARD_IN, T_CARD_IN_END);

    // 4. LOGO — magenta placeholder; centered on end card
    var logoLayer = makeSolid(comp, "LOGO", [0.9, 0.2, 0.6], logoW, logoH, w / 2, logoY);

    // 5. TEXT_CTA — dark text, centered below logo on end card (front)
    var ctaLayer = makeText(
        comp, "TEXT_CTA", "SHOP NOW",
        "CenturyGothic",
        w / 2, ctaY, ctaSize,
        ParagraphJustification.CENTER_JUSTIFY, [0.1, 0.1, 0.1], false
    );

    // ── Keyframe animation ────────────────────────────────────────────────────

    // BG_MEDIA: Ken Burns scale already set above

    // TEXT_TAGLINE: fade + slide up on entry; fade out before end card wipes in
    animOpacity(taglineLayer, [
        [0,                  0  ],
        [T_TAGLINE_IN,       0  ],
        [T_TAGLINE_IN_END,   100],
        [T_TAGLINE_OUT,      100],
        [T_TAGLINE_OUT_END,  0  ],
    ]);
    animPosition(
        taglineLayer,
        [leftX, taglineY + 20], [leftX, taglineY],
        T_TAGLINE_IN, T_TAGLINE_IN_END
    );

    // END_CARD: position wipe already set above (inPoint keeps it off-screen before 5s)

    // LOGO: hidden until end card is mostly in, then fade in
    animOpacity(logoLayer, [
        [0,           0  ],
        [T_LOGO_IN,   0  ],
        [T_LOGO_IN_END, 100],
    ]);

    // TEXT_CTA: hidden until end card wipe completes, then fade in
    animOpacity(ctaLayer, [
        [0,          0  ],
        [T_CTA_IN,   0  ],
        [T_CTA_IN_END, 100],
    ]);

    $.writeln("Created: " + spec.name);
}

// ── Save to templates/master_template.aep ────────────────────────────────────

var scriptFile   = new File($.fileName);
var projectRoot  = scriptFile.parent.parent;
var templatesDir = new Folder(projectRoot.fsName + "/templates");
if (!templatesDir.exists) templatesDir.create();
var saveFile = new File(templatesDir.fsName + "/master_template.aep");
project.save(saveFile);

$.writeln("\nMaster template saved: " + saveFile.fsName);
