import React from 'react';
import ReactDOM from 'react-dom/client';

import App from './App';
import PanelApp from './panel/PanelApp';
import ProofPage from './proof/ProofPage';
import './index.css';
import './panel/panel.css';

const path = window.location.pathname.replace(/\/$/, '') || '/';
// D5: the panel is the product; /proof shows the bench; the old population dashboard stays at /population.
const Root = path === '/proof' ? ProofPage : path === '/population' ? App : PanelApp;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
