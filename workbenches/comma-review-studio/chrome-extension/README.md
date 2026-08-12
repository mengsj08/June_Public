# Chrome Side Panel wrapper

This directory is source for a Manifest V3 wrapper around the shared Comma Editor bundle.

Build from the project root:

```bash
npm run build:chrome
```

Load `release/chrome-extension/` as an unpacked extension. Do not load this source directory directly because `dist/comma-editor.js` is generated during packaging.

Security boundary:

- no persistent host permissions;
- no cookies, debugger, webRequest, or browser-profile access;
- current-page extraction happens only after the user clicks `Capture page`;
- captured Markdown, comments, and events stay in `chrome.storage.local`;
- no remote scripts or model calls.
