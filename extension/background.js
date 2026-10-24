import { isOnshapeUrl } from "./url.js";

async function configureTab(tabId, url) {
  await chrome.sidePanel.setOptions({
    tabId,
    path: "panel.html",
    enabled: isOnshapeUrl(url),
  });
}

async function configureOpenTabs() {
  const tabs = await chrome.tabs.query({});
  await Promise.all(
    tabs
      .filter((tab) => tab.id !== undefined)
      .map((tab) => configureTab(tab.id, tab.url)),
  );
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  const url = changeInfo.url ?? tab.url;
  if (url === undefined) return;

  configureTab(tabId, url).catch((error) => {
    console.warn("Could not configure the Darwin side panel", error);
  });
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs
    .get(tabId)
    .then((tab) => configureTab(tabId, tab.url))
    .catch((error) => {
      console.warn("Could not configure the active Darwin tab", error);
    });
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .then(configureOpenTabs)
    .catch((error) => {
      console.warn("Could not initialize the Darwin side panel", error);
    });
});

chrome.runtime.onStartup.addListener(() => {
  configureOpenTabs().catch((error) => {
    console.warn("Could not restore the Darwin side panel", error);
  });
});
