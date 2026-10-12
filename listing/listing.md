# Listing checklist

Work through it in order and keep the answers; paste them in the submit form. Tick a box only after you have looked.

## 1. Is this a listing?

- [ ] The server already runs somewhere (hosted over https, or published for the buyer to run locally over stdio).
- [ ] FindAgent does not need to run it. If it does, this is a code agent, not a listing.
- [ ] You are the vendor or the owner of the server, or you act for them. You are listing a server to make it discoverable, not to claim someone else's.

## 2. The facts

- [ ] **Name and tagline** in the vendor's own terms (no marketing superlatives, no claim the server cannot back).
- [ ] **Description** of what the tools do and what they need (an account, a plan, a key).
- [ ] **Example prompts**: 1 to 5 things a person would really ask.
- [ ] **Authentication** in words: OAuth, or an API key in the vendor's own settings. FindAgent never takes the buyer's secret for a listing.
- [ ] **Logo**: the vendor's own brand mark only. Never a person's avatar. When none is safe the platform draws a generated mark.
- [ ] **No price.** A listing is free; any commercial relationship is between the buyer and the vendor. A priced listing is refused.
- [ ] **No category.** A listing is not categorised.

## 3. Hosted server

- [ ] The endpoint is an `https://` MCP URL.
- [ ] An anonymous `initialize` and `tools/list` against it with a real MCP client. Write down what came back:
  - a result with tools: say how many and whether the list is complete;
  - `401` or `403` with a `WWW-Authenticate` header: a real auth gate, and the header names the resource;
  - `401` alone: ambiguous, check the host serves MCP at all;
  - `200` with `text/html`: that is a web page, not an MCP server.
- [ ] You can create a DNS TXT record on the exact endpoint host (for the claim, section 5).

## 4. Local server

- [ ] The source repository is public and the launch command is the vendor's documented one. Quote it.
- [ ] You have admin permission on that GitHub repository (push is not enough; for the claim, section 5).
- [ ] You checked the account that owns the repository is the vendor, not an unrelated person or fork.

## 5. Proving ownership (the claim)

The listing decides the proof, you do not choose.

- Hosted: a DNS TXT record named `_findagent-challenge.<endpoint host>` (the exact host, not the parent domain) with the value the claim panel or `findagent_claim_listing` gives you; then `findagent_verify_listing_claim`.
- Local: GitHub **admin** permission on the declared repository.

## 6. Before you submit

- [ ] Nothing in the entry promises run-time protections the buyer does not get: FindAgent's guardrails do not apply to a server it does not run.
- [ ] No secret, token or private URL in any text you paste.
- [ ] You read the third-party tool text once: it is scanned for secrets, injection and slurs, and fixing flagged text happens at the source server.
