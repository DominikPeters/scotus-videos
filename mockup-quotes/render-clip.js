// Render a short MP4 clip of the quote mockup, using the same frame plan as screenshot.js.
// Usage (needs the local server on port 8002; the repo's puppeteer loads with Node 18):
//   node mockup-quotes/render-clip.js CASE START END OUTPUT.mp4 [deviceScaleFactor]
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const puppeteer = require('puppeteer');

(async () => {
    const [caseNumber, startArg, endArg, output, scaleArg] = process.argv.slice(2);
    const start = parseFloat(startArg);
    const end = parseFloat(endArg);
    const clipLength = end - start;
    const framesDir = fs.mkdtempSync(path.join(require('os').tmpdir(), 'quote-clip-'));

    const browser = await puppeteer.launch({ headless: "new" });
    const page = await browser.newPage();
    page.on('pageerror', error => console.log('[page error]', error.message));
    await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: parseFloat(scaleArg || "1") });
    await page.goto(`http://localhost:8002/mockup-quotes/?case=${caseNumber}${process.env.QUERY || ''}`); // optional extra URL parameters via QUERY
    await page.waitForSelector('#loading-finished');
    await page.evaluate(async () => {
        showSplash();
        await document.fonts.ready;
        await Promise.all([...document.images].map(img => img.complete ? null : new Promise(r => { img.onload = img.onerror = r; })));
    });

    const list = [];
    let frame = 0;
    let time = 0; // seconds into the clip
    async function capture(duration) {
        const remaining = clipLength - time;
        if (remaining <= 0) {
            return false;
        }
        duration = Math.min(duration, remaining);
        const file = path.join(framesDir, `frame-${frame}.png`);
        await page.screenshot({ path: file });
        list.push(`file '${file}'\nduration ${duration.toFixed(3)}`);
        frame++;
        time += duration;
        return true;
    }

    // state at the start of the clip
    const firstDuration = await page.evaluate((start) => {
        seekTo(start);
        return nextBlockStart() - start;
    }, start);
    await capture(firstDuration);

    while (time < clipLength) {
        const response = await page.evaluate(() => {
            if (reachedLastTextBlock) {
                goToNextSection();
            }
            return nextTextBlock();
        });
        if (!await capture(response.duration)) {
            break;
        }
        for (const [scrollAmount, duration, quoteProgress] of response.frameInfo) {
            await page.evaluate((scrollAmount, quoteProgress) => {
                scrollTranscript(scrollAmount);
                if (quoteProgress !== undefined && quoteProgress !== null) {
                    setQuoteProgress(quoteProgress);
                }
            }, scrollAmount, quoteProgress);
            if (!await capture(duration)) {
                break;
            }
        }
    }
    await browser.close();

    // concat demuxer needs the last file repeated
    list.push(`file '${path.join(framesDir, `frame-${frame - 1}.png`)}'`);
    const listFile = path.join(framesDir, 'frames.txt');
    fs.writeFileSync(listFile, list.join('\n') + '\n');
    // silent track when the case's audio is not available locally
    const audio = fs.existsSync(`mp3/${caseNumber}.mp3`)
        ? ['-ss', String(start), '-t', String(clipLength), '-i', `mp3/${caseNumber}.mp3`]
        : ['-f', 'lavfi', '-t', String(clipLength), '-i', 'anullsrc=r=44100:cl=mono'];
    execFileSync('ffmpeg', ['-v', 'error', '-y',
        '-f', 'concat', '-safe', '0', '-i', listFile,
        ...audio,
        '-map', '0:v', '-map', '1:a',
        '-vf', 'fps=25,format=yuv420p', '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
        '-c:a', 'aac', '-b:a', '128k', '-t', String(clipLength), '-movflags', '+faststart',
        output], { stdio: 'inherit' });
    fs.rmSync(framesDir, { recursive: true });
    console.log(`${output}: ${frame} frames, ${clipLength.toFixed(1)} s`);
})();
