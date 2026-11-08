// TikTok Studio browser transfer. Publication requires an explicit worker mode.
const fs = require('node:fs');
const readline = require('node:readline');

async function checkpoint(value) {
  if (process.env.SCOTUS_TIKTOK_CHECKPOINTS !== '1') return;
  const input = readline.createInterface({input: process.stdin});
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {input.close(); reject(Error('Checkpoint acknowledgement missing'));}, 20000);
    input.once('line', line => {clearTimeout(timer); input.close(); line === 'ok' ? resolve() : reject(Error('Checkpoint rejected'));});
    process.stdout.write(JSON.stringify({checkpoint: value}) + '\n');
  });
}

async function finishPublicPost(page) {
  // Studio sometimes asks whether to post before its optional checks finish.
  await page.waitForFunction(() => location.pathname.includes('/content') ||
    (document.body.innerText.includes('Continue to post?') &&
      [...document.querySelectorAll('button')].some(el => el.innerText.trim() === 'Post now')),
    {timeout: 60000});
  if (await page.evaluate(() => location.pathname.includes('/content'))) return;
  await checkpoint({publish_confirmation_pending: true});
  await page.evaluate(() => {
    if (!document.body.innerText.includes('Continue to post?') ||
        !document.body.innerText.includes("We're still checking your video")) throw Error('Unknown posting confirmation');
    const matches = [...document.querySelectorAll('button')].filter(el => el.innerText.trim() === 'Post now' && !el.disabled);
    if (matches.length !== 1) throw Error('Posting confirmation is ambiguous');
    matches[0].click();
  });
}

async function main() {
  const puppeteer = require('puppeteer');
  const [sessionPath, videoPath, captionPath, outputPath, editName, mode = 'draft'] = process.argv.slice(2);
  if (!['draft', 'publish', 'reconcile_draft', 'reconcile_publish'].includes(mode)) throw Error('Invalid TikTok mode');
  const session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
  const caption = fs.readFileSync(captionPath, 'utf8');
  const cookies = session.cookies;
  if (!Array.isArray(cookies) || !cookies.some(c => c.name === 'sessionid')) throw Error('Invalid session');
  const browser = await puppeteer.launch({headless: true, executablePath: '/usr/bin/chromium',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--lang=en-GB']});
  const page = await browser.newPage();
  const result = {published: false, saved: false, step: 'session'};
  const save = () => fs.writeFileSync(outputPath, JSON.stringify(result));
  const complete = async published => {
    await page.waitForFunction((text, isPost) => location.pathname.includes('/content') &&
      (new URLSearchParams(location.search).get('tab') === 'draft') !== isPost &&
      document.body.innerText.replace(/\s+/g, ' ').includes(text.replace(/\s+/g, ' ').trim()),
      {timeout: 60000}, caption, published);
    result.step = 'complete'; result.published = published; result.saved = !published;
    await checkpoint({draft_pending: false, publish_pending: false, publish_confirmation_pending: false, saved: result.saved, published, caption});
  };
  try {
    await page.setViewport({width: 1440, height: 1100});
    // Do not log cookie values, network headers, browser storage or console output.
    await page.setCookie(...cookies.map(({name, value}) => ({name, value, domain: '.tiktok.com', path: '/', secure: true})));
    if (mode.startsWith('reconcile_')) {
      await page.goto('https://www.tiktok.com/tiktokstudio/content' + (mode === 'reconcile_draft' ? '?tab=draft' : ''), {waitUntil: 'domcontentloaded', timeout: 60000});
      result.step = 'reconcile'; save(); await complete(mode === 'reconcile_publish'); return;
    }
    await page.goto(editName ? 'https://www.tiktok.com/tiktokstudio/content?tab=draft' :
      'https://www.tiktok.com/tiktokstudio/upload?from=webapp&tab=video', {waitUntil: 'domcontentloaded', timeout: 60000});
    if (editName) {
      result.step = 'find_existing_draft'; save();
      await page.waitForFunction(name => [...document.querySelectorAll('*')].some(el =>
        !el.children.length && el.textContent.trim() === name), {timeout: 45000}, editName);
      await page.evaluate(name => {
        const matches = [...document.querySelectorAll('*')].filter(el =>
          !el.children.length && el.textContent.trim() === name);
        if (matches.length !== 1) throw Error('Draft identity is ambiguous');
        let row = matches[0];
        while (row && row.querySelectorAll('button').length < 3) row = row.parentElement;
        if (!row || row.querySelectorAll('button').length !== 3) throw Error('Draft edit action unavailable');
        // Studio's draft row actions are edit, split and delete, in that order.
        row.querySelector('button').click();
      }, editName);
    } else {
      result.step = 'upload_form'; save();
      await page.waitForSelector('input[type=file]', {timeout: 45000});
      result.step = 'upload'; save();
      await (await page.$('input[type=file]')).uploadFile(videoPath);
    }
    await page.waitForSelector('[contenteditable=true]', {timeout: 60000});
    await page.waitForFunction(() => /Uploaded\s*[（(]/.test(document.body.innerText), {timeout: 90000});
    result.step = 'caption'; save();
    await page.evaluate(() => [...document.querySelectorAll('button')].find(el => el.innerText.trim() === 'Got it')?.click());
    const editor = await page.$('[contenteditable=true]');
    // Clicking the center of TikTok's large editor can leave focus on the page.
    // Focus the editable itself and select only its contents before key input.
    await editor.evaluate(el => {
      el.focus();
      if (document.activeElement !== el) throw Error('Caption editor did not take focus');
    });
    // The rich editor can reset a DOM selection during hydration. Clear using
    // native key events and verify emptiness rather than trusting that selection.
    await page.keyboard.down('Control'); await page.keyboard.press('End'); await page.keyboard.up('Control');
    for (let i = 0; i < 4000 && await editor.evaluate(el => el.innerText.trim().length > 0); i++) {
      await page.keyboard.press('Backspace');
    }
    if (await editor.evaluate(el => el.innerText.trim().length > 0)) throw Error('Caption did not clear');
    await page.keyboard.type(caption);
    await page.waitForFunction(text => document.querySelector('[contenteditable=true]')?.innerText.trim() === text,
      {timeout: 10000}, caption);
    await page.keyboard.press('Tab');
    result.step = mode === 'publish' ? 'publish' : 'save_draft'; save();
    if (mode === 'publish' && !await page.evaluate(() => /Who can see this post\s+Everyone/.test(document.body.innerText))) throw Error('Public visibility is not selected');
    const buttons = await page.$$('button');
    const drafts = [];
    for (const button of buttons) {
      if (await button.evaluate((el, label) => el.innerText.trim() === label && !el.disabled, mode === 'publish' ? 'Post' : 'Save draft')) drafts.push(button);
    }
    if (drafts.length !== 1) throw Error('Transfer action not available');
    await checkpoint(mode === 'publish' ? {publish_pending: true} : {draft_pending: true});
    // Avoid a coordinate click racing Studio's animated scroll to the footer.
    await drafts[0].evaluate(el => el.click());
    if (mode === 'publish') await finishPublicPost(page);
    await complete(mode === 'publish');
  } catch (error) {
    result.error_type = error.name;
    result.editor_state = await page.$$eval('[contenteditable=true]', elements => elements.map(el => ({
      tag: el.tagName, role: el.getAttribute('role'), visible: !!(el.offsetWidth || el.offsetHeight),
      focused: el === document.activeElement, text: el.innerText.slice(0, 120)
    }))).catch(() => []);
    // Bounded visible text diagnoses login/challenges without exporting cookies.
    result.visible_text = (await page.evaluate(() => document.body.innerText).catch(() => '')).slice(0, 6000);
  } finally {
    await page.screenshot({path: outputPath + '.png', fullPage: false}).catch(() => {});
    save(); await browser.close(); closeCheckpointChannel();
  }
  if (!result.saved && !result.published) process.exitCode = 1;
}
function closeCheckpointChannel() {
  if (process.env.SCOTUS_TIKTOK_CHECKPOINTS === '1') process.stdin.destroy();
}
module.exports = {checkpoint, closeCheckpointChannel, finishPublicPost};
if (require.main === module) main().catch(() => { closeCheckpointChannel(); console.error('TikTok browser worker could not start'); process.exitCode = 1; });
