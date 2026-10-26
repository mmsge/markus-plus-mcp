# markus-plus-mcp
MCP-server for markus.plus

> **Pensjonert.** Denne tenesta er ikkje lenger i drift, og Render-jobben er fjerna.
> Bruk `get_garden_page` og `get_garden_pages` i [activitypub-mcp](https://github.com/mmsge/activitypub-mcp)
> for å lesa markus.plus. Sider som ikkje er ferdig rendra endå vert dessutan løyste av
> [markus-plus-cloudflare-worker](https://github.com/mmsge/markus-plus-cloudflare-worker),
> så vanleg henting av markus.plus gir òg innhaldet.
>
> Koden står att som referanse.

## Korleis sider vert lesne

Sidetekst, metadata og sideliste vert henta direkte frå Obsidian Publish (indeksen og rå markdown), utan nettlesar. Det gjer at nye notat er tilgjengelege med éin gong, sjølv om den ferdig-rendra sida framleis seier «Not Found». Indeksen vert bufra i 30 minutt, og ved ukjend sti vert han oppdatert éin gong (maks ein gong i minuttet). Ukjende stiar gir feilen `Page not found`. Playwright vert berre brukt som reserve når indeksen ikkje er tilgjengeleg.
