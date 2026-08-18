/** Writes the view out as plain pages so it can be opened in a browser and looked at.
 *
 *  A webview is a browser, so the only thing missing outside VS Code is the theme: the `--vscode-*`
 *  variables the editor injects. Those are supplied here from the real Dark+ and Light+ values, so
 *  what renders in this harness is what renders in the panel — the same document, same CSP, same
 *  nonce, nothing stubbed.
 *
 *      node out-preview.js <outdir>
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { renderWorkplace } from "../index";
import { fixture, fixtureMoved } from "./fixture";

const DARK = `
--vscode-editor-background:#1f1f1f;--vscode-editor-foreground:#cccccc;--vscode-foreground:#cccccc;
--vscode-descriptionForeground:#9d9d9d;--vscode-widget-border:#3c3c3c;--vscode-focusBorder:#0078d4;
--vscode-charts-blue:#4daafc;--vscode-charts-purple:#b180d7;--vscode-charts-yellow:#d7ba7d;
--vscode-charts-green:#89d185;--vscode-charts-orange:#d18616;--vscode-charts-red:#f14c4c;
--vscode-errorForeground:#f14c4c;
--vscode-font-family:"Segoe WPC","Segoe UI",system-ui,-apple-system,sans-serif;`;

const LIGHT = `
--vscode-editor-background:#ffffff;--vscode-editor-foreground:#3b3b3b;--vscode-foreground:#3b3b3b;
--vscode-descriptionForeground:#767676;--vscode-widget-border:#d4d4d4;--vscode-focusBorder:#0090f1;
--vscode-charts-blue:#1a85ff;--vscode-charts-purple:#652d90;--vscode-charts-yellow:#b89500;
--vscode-charts-green:#388a34;--vscode-charts-orange:#d18616;--vscode-charts-red:#e51400;
--vscode-errorForeground:#e51400;
--vscode-font-family:"Segoe WPC","Segoe UI",system-ui,-apple-system,sans-serif;`;

/** The editor sets the theme variables on the document element and a class on the body. Injected
 *  the same way here, after the view's own stylesheet, exactly as VS Code does. */
function themed(html: string, vars: string, klass: string): string {
  return html
    .replace("</head>", `<style>:root{${vars}}</style></head>`)
    .replace("<body>", `<body class="${klass}">`);
}

function main(): void {
  const out = process.argv[2] || ".";
  mkdirSync(out, { recursive: true });

  const pages: [string, string][] = [
    ["dark.html", themed(renderWorkplace(fixture(), "devnonce123"), DARK, "vscode-dark")],
    ["light.html", themed(renderWorkplace(fixture(), "devnonce123"), LIGHT, "vscode-light")],
    ["move-a.html", themed(renderWorkplace(fixture(), "devnonce123"), DARK, "vscode-dark")],
    ["move-b.html", themed(renderWorkplace(fixtureMoved(), "devnonce123"), DARK, "vscode-dark")],
    ["empty.html", themed(renderWorkplace({ workers: [], at: Date.now() }, "devnonce123"), DARK, "vscode-dark")],
  ];
  for (const [name, html] of pages) {
    writeFileSync(join(out, name), html, "utf8");
    console.log(`${name}  ${(html.length / 1024).toFixed(1)} kB`);
  }
}

main();
