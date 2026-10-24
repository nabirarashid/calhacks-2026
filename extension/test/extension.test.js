import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { dashboardPanelUrl, isOnshapeUrl } from "../url.js";

const extensionRoot = new URL("../", import.meta.url);

test("manifest declares a scoped MV3 side panel", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("manifest.json", extensionRoot), "utf8"),
  );

  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.side_panel.default_path, "panel.html");
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.ok(manifest.permissions.includes("tabs"));
  assert.deepEqual(manifest.host_permissions, ["https://cad.onshape.com/*"]);
  assert.match(
    manifest.content_security_policy.extension_pages,
    /frame-src http:\/\/localhost:5173/,
  );
});

test("only HTTPS cad.onshape.com URLs are supported", () => {
  assert.equal(
    isOnshapeUrl("https://cad.onshape.com/documents/abc/w/def/e/ghi"),
    true,
  );
  assert.equal(isOnshapeUrl("http://cad.onshape.com/documents/abc"), false);
  assert.equal(isOnshapeUrl("https://evil.example/?cad.onshape.com"), false);
  assert.equal(isOnshapeUrl("not a url"), false);
});

test("dashboard URL carries the complete document URL", () => {
  const documentUrl =
    "https://cad.onshape.com/documents/a/w/b/e/c?renderMode=0&uiState=xyz";
  const panelUrl = new URL(dashboardPanelUrl(documentUrl));

  assert.equal(panelUrl.origin, "http://localhost:5173");
  assert.equal(panelUrl.pathname, "/panel");
  assert.equal(panelUrl.searchParams.get("doc"), documentUrl);
});

test("panel uses extension-owned scripts instead of inline JavaScript", async () => {
  const html = await readFile(new URL("panel.html", extensionRoot), "utf8");

  assert.match(html, /<script type="module" src="panel\.js"><\/script>/);
  assert.doesNotMatch(html, /<script(?![^>]+src=)[^>]*>/);
});
