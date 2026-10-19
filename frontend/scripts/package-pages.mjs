import { cp, mkdir, rm, writeFile } from "node:fs/promises";
// Copy only static adapters into the publication artifact; exclude the live build.
const destination = new URL("../pages/", import.meta.url);
// This exact ignored directory is generated solely by this script.
await rm(destination, {recursive: true, force: true});
await mkdir(destination, {recursive: true});
for (const mode of ["evidence", "sandbox"]) {
  await cp(new URL(`../dist/${mode}/`, import.meta.url), new URL(`${mode}/`, destination), {recursive: true});
}
await writeFile(new URL("index.html", destination), '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Operational AI evidence</title><h1>Operational AI evidence</h1><p>Authored fixtures. All actions are simulations. No backend API calls.</p><p><a href="evidence/">Evidence replay</a> · <a href="sandbox/">Dummy sandbox</a></p></html>\n');
await writeFile(new URL(".nojekyll", destination), "");
console.log("Static publication artifact: frontend/pages (evidence + sandbox only)");
