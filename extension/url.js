const ONSHAPE_ORIGIN = "https://cad.onshape.com";
const DASHBOARD_PANEL_URL = "http://localhost:5173/panel";

export function isOnshapeUrl(value) {
  if (!value) return false;

  try {
    return new URL(value).origin === ONSHAPE_ORIGIN;
  } catch {
    return false;
  }
}

// Onshape rewrites the query (?uiState=...) as you click around; only the path names the document
// and element, so the panel reloads only when the path changes (a reload would drop the session view).
export function documentKey(value) {
  try {
    const url = new URL(value);
    return url.origin + url.pathname;
  } catch {
    return null;
  }
}

export function dashboardPanelUrl(documentUrl) {
  const url = new URL(DASHBOARD_PANEL_URL);
  url.searchParams.set("doc", documentUrl);
  return url.toString();
}
