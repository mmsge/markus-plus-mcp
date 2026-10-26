# markus-plus-mcp
MCP-server for markus.plus

## Deploy til Render

1. Gå til [render.com](https://render.com) og opprett eit nytt prosjekt.
2. Kopla til GitHub-repoet ditt.
3. Vel **Web Service** som tenestetype.
4. Set runtime til **Docker**.
5. Vel **gratis plan** (Free).
6. Klikk **Deploy**.
7. Kopier den offentlege URL-en Render tildeler tenesta.
8. Legg URL-en inn i Claude.ai under **Settings → Connectors**.

## Korleis sider vert lesne

Sidetekst, metadata og sideliste vert henta direkte frå Obsidian Publish (indeksen og rå markdown), utan nettlesar. Det gjer at nye notat er tilgjengelege med éin gong, sjølv om den ferdig-rendra sida framleis seier «Not Found». Indeksen vert bufra i 30 minutt, og ved ukjend sti vert han oppdatert éin gong (maks ein gong i minuttet). Ukjende stiar gir feilen `Page not found`. Playwright vert berre brukt som reserve når indeksen ikkje er tilgjengeleg.
