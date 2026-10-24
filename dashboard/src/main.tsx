import React from 'react';
import ReactDOM from 'react-dom/client';

import App from './App';
import PanelApp from './panel/PanelApp';
import './index.css';
import './panel/panel.css';

const path = window.location.pathname.replace(/\/$/, '') || '/';
const Root = path === '/proof' ? App : PanelApp;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
