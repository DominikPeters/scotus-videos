# Find advocate image candidates

Follow the policy instructions supplied above. Match the supplied advocate to the Court appearances and docket,
including firm/agency and location. A shared name is insufficient. Search official
firm/agency profiles first, then other reliable sources. LinkedIn profile photos
are explicitly permitted, as are portraits from news articles. For LinkedIn,
verify the profile's employment, firm/agency and location against the advocate's
identity evidence; a matching name alone is insufficient. Record the LinkedIn
profile as the identity/source URL and return the actual portrait image URL.
If native web search cannot expose a useful portrait, call
photo_fetch_authenticated with a known LinkedIn profile URL when that tool is
available. It fetches the profile using privately stored owner cookies and returns
profile evidence and portrait URLs; inspect these before selecting an image.
Use authenticated access only if an authenticated tool has actually been supplied;
web search does not inherit the owner's local Chrome session. Never request or
include session cookies in your output, private notes, or image URLs. If a profile
is inaccessible, report its URL and the access problem privately and try other
sources. Return up to three actual
image URLs and the corresponding identity/profile URL. A firm/agency logo is a
candidate when no portrait is accessible. Do not invent an image URL or mark a
new image approved. Approval is a dashboard action. Uncertainty and HTTP failures
are private notes; do not add any viewer-facing disclaimer.

Return {"candidates":[{"url":"https://...","source_url":"https://...",
"identity_source_url":"https://...","kind":"photo|logo","private_note":"..."}],
"private_notes":[]}. An empty candidates array is valid and requires operator review.
