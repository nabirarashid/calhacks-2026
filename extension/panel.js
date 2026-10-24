import { dashboardPanelUrl, isOnshapeUrl } from "./url.js";

const iframe = document.querySelector("#darwin-panel");
const status = document.querySelector("#status");

function showStatus(message) {
  status.querySelector("p").textContent = message;
  status.hidden = false;
  iframe.hidden = true;
  iframe.removeAttribute("src");
}

function showPanel(documentUrl) {
  iframe.src = dashboardPanelUrl(documentUrl);
  iframe.hidden = false;
  status.hidden = true;
}

async function refresh() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !isOnshapeUrl(tab.url)) {
    showStatus("Darwin is available on cad.onshape.com.");
    return;
  }

  showPanel(tab.url);
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!tab.active || changeInfo.url === undefined) return;
  refresh().catch(() => showStatus("Could not read the active Onshape document."));
});

chrome.tabs.onActivated.addListener(() => {
  refresh().catch(() => showStatus("Could not read the active Onshape document."));
});

refresh().catch(() => showStatus("Could not read the active Onshape document."));
