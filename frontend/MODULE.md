# Frontend module

The current frontend is `web/`: static HTML/CSS/JavaScript SPA served by FastAPI at `/`. It is not a Streamlit application.

`app.js` owns navigation, auth/session recovery, entry/exit and drafts. Camera, billing, MB and 3D decoration have separate modules. `runtime-notice.css` styles the explicit offline-demo label; `api/web.py` inserts it only in isolated demo mode.

Keep UI permission hints aligned with server RBAC. Do not treat hidden controls as authorization. Do not reuse an OCR response after the image, account or request generation changes. Keep keyboard labels, error recovery, reduced motion and mobile layout. Tests use Node's runner in `tests/test_*.cjs`.
