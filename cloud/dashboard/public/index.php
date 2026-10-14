<?php
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https://github.com");
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video jobs</title><link rel="stylesheet" href="dashboard.css?v=16">
  <script src="dashboard.js?v=23" defer></script>
</head>
<body>
<header><h1>Video jobs</h1><button id="logout" hidden>Sign out</button></header>
<main>
  <p id="message" role="status" aria-live="polite">Connecting…</p>
  <p id="action-status" role="status" aria-live="polite" hidden><span class="spinner" aria-hidden="true"></span><span id="action-label"></span></p>
  <section id="signin" hidden>
    <h2 id="signin-title">Sign in</h2>
    <p id="signin-note">Use your passkey to open the dashboard.</p>
    <button id="signin-button">Sign in with a passkey</button>
  </section>
  <div id="dashboard" hidden>
    <div class="toolbar"><span id="pipeline-status"></span><button id="pause">Resume automatic work</button><button id="dispatch">Check for work</button><button id="refresh">Refresh</button></div>
    <section>
      <h2>Recordings</h2>
      <div class="table-wrap"><table><thead><tr><th>Case</th><th class="job-date-column">Argument date</th><th>Status</th><th>Progress</th><th>Actions</th></tr></thead><tbody id="jobs"></tbody></table></div>
      <p id="empty" hidden>No recordings queued.</p>
      <div id="job-detail" hidden></div>
    </section>
    <section><h2>Reviews</h2><p id="review-empty">No reviews yet.</p><div id="reviews"></div></section>
    <section>
      <h2>Recovery</h2>
      <p id="recovery-empty">No recovery tasks.</p>
      <p id="repair-budget" class="note"></p>
      <div id="recoveries"></div>
    </section>
    <section>
      <details id="credentials-details"><summary>Credentials and access</summary>
      <p id="cloud-status">Checking cloud connection…</p>
      <div class="table-wrap"><table><thead><tr><th>Service</th><th>Status</th><th>Last saved</th><th>Actions</th></tr></thead><tbody id="secrets"></tbody></table></div>
      <div id="connection-guide" class="steps" hidden aria-live="polite"></div>
      <details id="credential-import-details"><summary>Import a credential file</summary>
      <form id="secret-form">
        <div class="fields"><label>Service<select name="name"><option value="youtube">YouTube</option><option value="codex">Codex</option><option value="spotify">Spotify</option><option value="youtube_client">YouTube browser client</option></select></label><label>Credential file<input name="file" type="file" accept=".json,application/json" required></label></div>
        <p class="note">Choose a fresh credentials.json or auth.json file. Saved credentials are not returned to this page.</p>
        <button type="submit">Replace credential</button>
      </form>
      </details>
      <button id="add-passkey">Add another passkey</button>
      </details>
    </section>
    <section>
      <details id="queue-details"><summary>Queue a recording</summary>
      <form id="queue-form">
        <div class="fields"><label>Docket<input name="docket" required placeholder="25-332" pattern="[0-9]{2}(-[0-9]+|[A-Z][0-9]+)"></label><label>Argument date<input name="argument_date" type="date" required></label></div>
        <label>Case name<input name="case_name" required maxlength="300"></label>
        <label>Video title<input name="title" required maxlength="100" placeholder="Oral Argument on …: …"></label>
        <label>Official transcript link<input name="pdf_url" type="url" required></label>
        <label>Official audio link<input name="audio_url" type="url" required></label>
        <button type="submit">Queue recording</button>
      </form>
      </details>
    </section>
    <section><details id="activity-details"><summary>Recent activity</summary><ol id="events"></ol></details></section>
  </div>
</main>
</body></html>
