---
hide:
  - toc
---

# API reference

Every endpoint of the Fab Dispatch API, generated from the code (OpenAPI 3).

- **Try it interactively** on the running app: [fab-dispatch.vercel.app/api/docs](https://fab-dispatch.vercel.app/api/docs),
  or **http://localhost:5173/api/docs** locally.
- **Authentication:** sign in to the app, then send the session's token as `Authorization: Bearer …`.
  Help, health and sign-in configuration are public.
- **Errors** share one envelope: `{"error": {"code", "message", "request_id"}}`.
- **Raw schema:** [openapi.json](openapi.json)

<div id="redoc-container"></div>
<script src="https://cdn.jsdelivr.net/npm/redoc@2.5.1/bundles/redoc.standalone.js"></script>
<script>
  Redoc.init('openapi.json', {
    hideDownloadButton: false, expandResponses: '200,201', theme: {
      colors: { primary: { main: '#ef6f2e' } },
      typography: { fontFamily: 'Geist, system-ui, sans-serif', headings: { fontFamily: 'Geist, system-ui, sans-serif' }, code: { fontFamily: 'Geist Mono, monospace' } },
      sidebar: { backgroundColor: '#f5f5f5' }
    }
  }, document.getElementById('redoc-container'))
</script>
