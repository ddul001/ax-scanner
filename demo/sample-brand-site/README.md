# Velora demo brand site

A minimal fictional car-brand website (plain HTML plus a small JS filter) used to prove that the scanner's checks and the
`ux.j_dealer` agent journey can pass. Serve it with `python -m http.server 8080 --directory demo/sample-brand-site`.

The dealer network is in the HTML; the script only filters it by city. Regenerate the pages with the generator used to create them.

## Agent declarations are placeholders
- `/.well-known/agent-card.json` follows the AAP 3.0 schema (`schemas/agent-card.schema.json` of the upstream auto-agent-protocol repository) and declares one skill,
  `dealer.information`. The interface URL (`/a2a`) and the MCP URL (`/mcp`) are placeholders: **there is no live agent endpoint**.
  `public_read` is `false` for that reason.
- `/.well-known/poppy.json` is a minimal valid Poppy document that points to the card.
- The scanner only checks that the card exists, is JSON and declares the AAP extension. It does not call the endpoints.
