import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { initAnalytics } from './analytics';
import './deploy-maintenance.css';

initAnalytics();

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

window.__OPEN_EMS_APP_MOUNTED = true;
document.getElementById('deploy-maintenance-bootstrap')?.remove();
