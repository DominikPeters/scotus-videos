const fs = require('fs');

const puppeteer = require('puppeteer');

function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const secondsLeft = seconds % 60;
    // two digits for minutes, two digits for seconds, no decimal
    return `${minutes.toString().padStart(2, '0')}:${secondsLeft.toFixed(0).padStart(2, '0')}`;
}

(async () => {

    // Check if script was called with --vertical option
    const verticalMode = process.argv.includes('--vertical');
    if (verticalMode) {
        console.log("Vertical mode enabled.");
    }

    const framesDir = verticalMode ? 'frames-vertical' : 'frames';

    // Get case number from case_number.txt
    const caseNumber = fs.readFileSync('case_number.txt', 'utf8').trim();

    // ensure folder exists
    if (!fs.existsSync(`${framesDir}/${caseNumber}`)) {
        fs.mkdirSync(`${framesDir}/${caseNumber}`, { recursive: true });
    }

    // open a text file with frame durations for ffmpeg
    const frameDurations = fs.openSync(`${framesDir}/${caseNumber}/frame-durations.txt`, 'w');

    const browser = await puppeteer.launch({ headless: "new", protocolTimeout: 240000 });
    // const browser = await puppeteer.launch();
    const page = await browser.newPage();

    page.on('console', async (msg) => {
        const values = await Promise.all(
            msg.args().map((arg) => arg.jsonValue().catch(() => '[unserializable]'))
        );
        console.log(`[browser:${msg.type()}]`, ...values);
    });

    // Set the viewport's width and height
    if (!verticalMode) {
        await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 2 }); // 4K resolution
    } else {
        await page.setViewport({ width: 1080, height: 1920 });
    }

    // check that files exist
    const interactionsCheck = JSON.parse(fs.readFileSync(`json/${caseNumber}-interactions.json`));
    let neededFiles = [`json/${caseNumber}.json`, `json/${caseNumber}-interactions.json`];
    
    // Check for audio files - handle both single and multiple arguments
    if (interactionsCheck.arguments && interactionsCheck.arguments.length > 1) {
        // Multiple arguments: check numbered audio files
        for (let i = 0; i < interactionsCheck.arguments.length; i++) {
            neededFiles.push(`json/${caseNumber}-audio-${i}.json`);
        }
    } else {
        // Single argument: check standard audio file
        neededFiles.push(`json/${caseNumber}-audio.json`);
    }
    
    for (let file of neededFiles) {
        if (!fs.existsSync(file)) {
            console.log(`File ${file} does not exist.`);
            process.exit(1);
        }
    }

    if (!verticalMode) {
        await page.goto(`http://localhost:8002/?case=${caseNumber}`);
    } else {
        await page.goto(`http://localhost:8002/vertical.html?case=${caseNumber}`);
    }

    // wait for #loading-finished to appear
    await page.waitForSelector('#loading-finished');

    let totalTime = 0;

    // thumbnail
    if (!verticalMode) {
        console.log(`Thumbnail.`);
        await page.screenshot({ path: `thumbnails/${caseNumber}.png` });
    }

    // splash screen
    await page.evaluate(() => { showSplash(); });
    let i = 0;
    await takeScreenshot(i);
    console.log(`Splash screen.`);
    

    async function takeScreenshot(frameNumber) {
        const fileName = `${framesDir}/${caseNumber}/frame-${frameNumber}.png`;
        if (!fs.existsSync(fileName)) {
            await page.screenshot({ path: fileName });
        }
    }

    await page.evaluate(() => { goToNextSection(); });
    console.log("First section.");
    
    let currentArgumentIndex = 0;

    while (true) {
        const response = await page.evaluate(() => {
            return nextTextBlock();
        });

        if (i == 0) {
            // decide on length of splash screen (min(5 sec, duration of second frame))
            if (response.duration < 5) {
                console.log(`  Warning: First frame duration is less than 5 seconds.`);
                console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: ${response.duration.toFixed(2)}`);
                fs.writeSync(frameDurations, `file frame-${i}.png\nduration ${response.duration.toFixed(2)}\n`);
                totalTime += response.duration;
                response.duration = 0;
            } else {
                console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 5`);
                fs.writeSync(frameDurations, `file frame-${i}.png\nduration 5\n`);
                response.duration -= 5;
            }
            i++;
        }

        await takeScreenshot(i);
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
                await takeScreenshot(i);
                // console.log(`  frame-${i}.png. duration: ${duration.toFixed(2)}`);
                process.stdout.write(` ${duration.toFixed(2)}`);
                fs.writeSync(frameDurations, `file frame-${i}.png\nduration ${duration.toFixed(2)}\n`);
                totalTime += duration;
                i++;
            }
        }
        process.stdout.write('\n');
        if (response.goToNextSection) {
            // Check if we're transitioning to a new argument
            const nextSectionInfo = await page.evaluate((currentSection) => {
                const nextSection = currentSection + 1;
                if (nextSection < sectionsObject.length) {
                    const currentArgIndex = sectionsObject[currentSection].argument_index || 0;
                    const nextArgIndex = sectionsObject[nextSection].argument_index || 0;
                    return {
                        isNewArgument: nextArgIndex > currentArgIndex,
                        argumentTitle: sectionsObject[nextSection].argument_title,
                        argumentIndex: nextArgIndex
                    };
                }
                return { isNewArgument: false };
            }, response.currentSection || 0);
            
            if (nextSectionInfo.isNewArgument) {
                // Show argument transition screen
                console.log(`Argument transition: ${nextSectionInfo.argumentTitle}`);
                await page.evaluate((argumentTitle) => {
                    announceNextArgument(argumentTitle);
                }, nextSectionInfo.argumentTitle);
                
                await takeScreenshot(i);
                console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 3`);
                fs.writeSync(frameDurations, `file frame-${i}.png\nduration 3\n`);
                totalTime += 3;
                i++;
                
                currentArgumentIndex = nextSectionInfo.argumentIndex;
            }
            
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
        await takeScreenshot(i);
        console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 5`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration 5\n`);
        i++;
    }

    const interactions = JSON.parse(fs.readFileSync(`json/${caseNumber}-interactions.json`));
    if (interactions.announcements != undefined && interactions.announcements.length > 0) {
        // announcements
        console.log("Announcements.");
        await page.evaluate(() => {
            announceOpinionAnnouncements();
        });
        await takeScreenshot(i);
        console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 8`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration 8\n`);
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
        
                await takeScreenshot(i);
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
                        await takeScreenshot(i);
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
        await takeScreenshot(i);
        console.log(`  ${formatTime(totalTime)} frame-${i}.png. duration: 5`);
        fs.writeSync(frameDurations, `file frame-${i}.png\nduration 5\n`);
        i++;
    }

    fs.writeSync(frameDurations, `file frame-${i-1}.png`); // need to repeat the last frame
    fs.closeSync(frameDurations);

    await browser.close();
})();
