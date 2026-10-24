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

export function dashboardPanelUrl(documentUrl) {
  const url = new URL(DASHBOARD_PANEL_URL);
  url.searchParams.set("doc", documentUrl);
  return url.toString();
}
