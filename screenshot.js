const fs = require('fs');

const puppeteer = require('puppeteer');

function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const secondsLeft = seconds % 60;
    // two digits for minutes, two digits for seconds, no decimal
    return `${minutes.toString().padStart(2, '0')}:${secondsLeft.toFixed(0).padStart(2, '0')}`;
}

(async () => {

    // Get case number from case_number.txt
    const caseNumber = fs.readFileSync('case_number.txt', 'utf8').trim();

    // ensure folder exists
    if (!fs.existsSync(`frames/${caseNumber}`)) {
        fs.mkdirSync(`frames/${caseNumber}`, { recursive: true });
    }

    // open a text file with frame durations for ffmpeg
    const frameDurations = fs.openSync(`frames/${caseNumber}/frame-durations.txt`, 'w');

    const browser = await puppeteer.launch({ headless: "new", protocolTimeout: 240000 });
    // const browser = await puppeteer.launch();
    const page = await browser.newPage();

    // Set the viewport's width and height
    await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 2 });

    // check that files exist
    const neededFiles = [`json/${caseNumber}.json`, `json/${caseNumber}-audio.json`, `json/${caseNumber}-interactions.json`];
    for (let file of neededFiles) {
        if (!fs.existsSync(file)) {
            console.log(`File ${file} does not exist.`);
            process.exit(1);
        }
    }

    await page.goto(`http://localhost:8002/?case=${caseNumber}`);

    // wait for #loading-finished to appear
    await page.waitForSelector('#loading-finished');

    let totalTime = 0;

    // thumbnail
    console.log(`Thumbnail.`);
    await page.screenshot({ path: `thumbnails/${caseNumber}.png` });

    // splash screen
    await page.evaluate(() => { showSplash(); });
    let i = 0;
    await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
    console.log(`Splash screen.`);
    console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 8`);
    fs.writeSync(frameDurations, `file frame-${i}.png\nduration 5\n`);
    totalTime += 5;
    i++;


    await page.evaluate(() => { goToNextSection(); });
    console.log("First section.");

    while (true) {
        const response = await page.evaluate(() => {
            return nextTextBlock();
        });

        if (i == 1) {
            // subtract 5 seconds from the first frame (splash screen)
            if (response.duration < 5) {
                throw "First frame duration is less than 5 seconds.";
            }
            response.duration -= 5;
        }

        if (i == 5) {
            break;
        }

        await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
        // don't end log with newline
        process.stdout.write(`  ${formatTime(totalTime)} frame-${i}.png. duration: ${response.duration.toFixed(2)}`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration ${response.duration.toFixed(2)}\n`);
        totalTime += response.duration;
        i++;
        if (response.frameInfo.length > 0) {
            // need to smoothly scroll
            for (let [scrollAmount, duration] of response.frameInfo) {
                await page.evaluate((scrollAmount) => {
                    scrollTranscript(scrollAmount);
                }, scrollAmount);
                await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
                // console.log(`  frame-${i}.png. duration: ${duration.toFixed(2)}`);
                process.stdout.write(` ${duration.toFixed(2)}`);
                fs.writeSync(frameDurations, `file frame-${i}.png\nduration ${duration.toFixed(2)}\n`);
                totalTime += duration;
                i++;
            }
        }
        process.stdout.write('\n');
        if (response.goToNextSection) {
            await page.evaluate(() => {
                goToNextSection();
            });
            console.log("Next section.");
        } else if (response.lastTurn) {
            break;
        }
    }

    // conclusion screen
    console.log("Conclusion.");
    const showingConclusion = await page.evaluate(() => {
        showConclusion();
    });
    if (showingConclusion) {
        await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
        console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 5`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration 5\n`);
        i++;
    }

    const interactions = JSON.parse(fs.readFileSync(`json/${caseNumber}-interactions.json`));
    if (interactions.announcements.length > 0) {
        // announcements
        console.log("Announcements.");
        await page.evaluate(() => {
            announceOpinionAnnouncements();
        });
        await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
        console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 3`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration 3\n`);
        i++;
        for (let j = 0; j < interactions.announcements.length; j++) {
            await page.evaluate((i) => {
                loadNextOpinionAnnouncement();
            });
            console.log(`Announcement ${j+1}.`);

            while (true) {
                const response = await page.evaluate(() => {
                    return nextTextBlock();
                });
        
                await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
                console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: ${response.duration.toFixed(2)}`);
                fs.writeSync(frameDurations, `file frame-${i}.png\nduration ${response.duration.toFixed(2)}\n`);
                totalTime += response.duration;
                i++;
                if (response.frameInfo.length > 0) {
                    // need to smoothly scroll
                    for (let [scrollAmount, duration] of response.frameInfo) {
                        await page.evaluate((scrollAmount) => {
                            scrollTranscript(scrollAmount);
                        }, scrollAmount);
                        await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
                        // console.log(`  frame-${i}.png. duration: ${duration.toFixed(2)}`);
                        fs.writeSync(frameDurations, `file frame-${i}.png\nduration ${duration.toFixed(2)}\n`);
                        totalTime += duration;
                        i++;
                    }
                }
                if (response.goToNextSection) {
                    await page.evaluate(() => {
                        goToNextSection();
                    });
                    console.log("Next section.");
                } else if (response.lastTurn) {
                    break;
                }
            }
        }
        // show conclusion screen again
        console.log("Conclusion.");
        await page.evaluate(() => {
            showConclusion();
        });
        await page.screenshot({ path: `frames/${caseNumber}/frame-${i}.png` });
        console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 5`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration 5\n`);
        i++;
    }

    fs.writeSync(frameDurations, `file frame-${i-1}.png`); // need to repeat the last frame
    fs.closeSync(frameDurations);

    await browser.close();
})();
