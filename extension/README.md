# Darwin Chrome side panel

1. Start the dashboard on `http://localhost:5173`.
2. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**.
3. Select this `extension/` directory.
4. Open a document on `https://cad.onshape.com` and click the Darwin toolbar icon.

The side panel is disabled on non-Onshape tabs. It passes the active Onshape URL to the
dashboard as `/panel?doc=<encoded URL>`; API credentials remain in the backend.

Run the zero-dependency checks with `npm test` from this directory.
