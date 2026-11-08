<?php
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https://github.com");
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Scotus videos</title>
  <meta name="theme-color" content="#f2f2f4" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Scotus videos">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="apple-touch-icon" href="icon-180.png?v=2">
  <link rel="icon" href="icon-192.png">
  <link rel="stylesheet" href="app.css?v=8">
  <script type="module" src="main.js?v=8"></script>
</head>
<body data-route="loading">
<header id="topbar" class="topbar"></header>
<div id="pull" class="pull" role="status" hidden></div>
<main id="app">
  <section id="signin"></section>
  <nav id="list" aria-label="Recordings"></nav>
  <article id="detail"></article>
</main>
<div id="toasts" aria-live="polite"></div>
</body>
</html>
