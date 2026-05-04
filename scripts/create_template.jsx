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
 * Each comp has:
 *   BG_MEDIA        (AV layer — solid placeholder, cyan tint)
 *   TEXT_TAGLINE    (text layer)
 *   TEXT_PRODUCT_NAME (text layer)
 *   TEXT_CTA        (text layer)
 *   LOGO            (solid placeholder, magenta tint)
 *
 * After running, add your keyframe animation to each comp and save as
 *   templates/yosuki_master_template.aep
 *
 * Duration: 8 seconds at 30fps
 */

var DURATION = 8;      // seconds
var FPS = 30;
var FRAME_DURATION = 1 / FPS;

var COMPS = [
    { name: "Billboard_970x250",    width: 970,  height: 250  },
    { name: "YouTube_1920x1080",    width: 1920, height: 1080 },
    { name: "Instagram_1080x1080",  width: 1080, height: 1080 },
];

function addSolidPlaceholder(comp, name, color, width, height) {
    var solid = comp.layers.addSolid(color, name, width, height, 1.0);
    solid.name = name;
    solid.inPoint = 0;
    solid.outPoint = DURATION;
    return solid;
}

function addTextLayer(comp, name, defaultText, yPos) {
    var textLayer = comp.layers.addText(defaultText);
    textLayer.name = name;
    textLayer.inPoint = 0;
    textLayer.outPoint = DURATION;
    // Center the text
    textLayer.property("Position").setValue([comp.width / 2, yPos]);
    var textDoc = textLayer.property("Source Text").value;
    textDoc.resetCharStyle();
    textDoc.fontSize = Math.max(18, comp.height * 0.06);
    textDoc.fillColor = [1, 1, 1];
    textDoc.justification = ParagraphJustification.CENTER_JUSTIFY;
    textLayer.property("Source Text").setValue(textDoc);
    return textLayer;
}

app.newProject();
var project = app.project;

for (var c = 0; c < COMPS.length; c++) {
    var spec = COMPS[c];
    var comp = project.items.addComp(
        spec.name, spec.width, spec.height, 1.0, DURATION, FPS
    );

    // BG_MEDIA — cyan placeholder at bottom of stack
    addSolidPlaceholder(comp, "BG_MEDIA", [0.1, 0.6, 0.8], spec.width, spec.height);

    // LOGO — magenta placeholder, small, bottom-center
    var logo = addSolidPlaceholder(comp, "LOGO", [0.9, 0.2, 0.6],
        Math.round(spec.width * 0.12), Math.round(spec.height * 0.18));
    logo.property("Position").setValue([spec.width / 2, spec.height * 0.82]);

    // TEXT_CTA — bottom area
    addTextLayer(comp, "TEXT_CTA", "SHOP NOW", spec.height * 0.88);

    // TEXT_TAGLINE — center
    addTextLayer(comp, "TEXT_TAGLINE", "OWN THE STAGE", spec.height * 0.45);

    // TEXT_PRODUCT_NAME — just below tagline
    addTextLayer(comp, "TEXT_PRODUCT_NAME", "YOSUKI SIGNATURE SAXOPHONE", spec.height * 0.58);

    $.writeln("Created composition: " + spec.name);
}

$.writeln("\nTemplate created with " + COMPS.length + " compositions.");
$.writeln("Next steps:");
$.writeln("  1. Add your keyframe animation to each composition.");
$.writeln("  2. Set the Output Module to H.264 MP4.");
$.writeln("  3. Save as: templates/yosuki_master_template.aep");
