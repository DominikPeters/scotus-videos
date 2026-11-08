let justices = [];
let case_data;
let audio_data;
let interactions_data;
let sectionsObject;
let announcements;
let announcementMode = false;
let mp3length;

let currentSection = -1;
let currentTurn = 0;
let currentTextBlock = 0;
let currentInteraction = -1;
let reachedLastTextBlock = false;
let currentOpinion = -1;

let quoteCues = [];
let circuitMapSvg = "";
let activeQuoteCue = null;
const QUOTE_FRAME_DURATION = 0.05; // 20 fps
const QUOTE_TRANSITION_FRAMES = 24; // 1.2 seconds

function setUpCase(caseNumber) {
    Promise.all([
        fetch(`http://localhost:8002/json/${caseNumber}.json`).then(response => response.json()),
        fetch(`http://localhost:8002/json/${caseNumber}-interactions.json`).then(response => response.json())
    ]).then((jsons) => {
        case_data = jsons[0];
        interactions_data = jsons[1];
        
        // Handle single vs multiple arguments
        let hasMultipleArguments = interactions_data.arguments && interactions_data.arguments.length > 1;
        
        if (hasMultipleArguments) {
            // Multiple arguments: load all argument JSONs and concatenate sections
            Promise.all(interactions_data.arguments.map(argument => 
                fetch(`http://localhost:8002/${argument.json}`).then(response => response.json()))).then(
                    (argumentJsons) => { 
                        // Concatenate all sections from all arguments
                        sectionsObject = [];
                        for (let argJson of argumentJsons) {
                            sectionsObject = sectionsObject.concat(argJson.transcript.sections);
                        }
                        finishSetup();
                    }
                );
        } else {
            // Single argument: load normally for backward compatibility
            fetch(`http://localhost:8002/json/${caseNumber}-audio.json`).then(response => response.json()).then(
                (audioData) => {
                    audio_data = audioData;
                    sectionsObject = audio_data.transcript.sections;
                    finishSetup();
                }
            );
        }
        
        function finishSetup() {
            let hasAnnouncements = interactions_data.announcements && interactions_data.announcements.length > 0;
            if (hasAnnouncements) {
                // for each announcement, load its json (filename: announcement["json"])
                Promise.all(interactions_data.announcements.map(announcement => 
                    fetch(`http://localhost:8002/${announcement.json}`).then(response => response.json()))).then(
                        (announcementsJsons) => { announcements = announcementsJsons; }
                    );
            }
            mp3length = parseInt(interactions_data["mp3_length"]);
            // show title
            document.getElementById('case-name').innerHTML = case_data.name;
            document.getElementById('docket-number').innerHTML = "[" + case_data.docket_number + "]";
            document.getElementById('subtitle').innerHTML = interactions_data.dates;
            buildBench(case_data);
            // setUpSection(0);
            showThumbnail(hasAnnouncements);
            // announceOpinionAnnouncements();
            loadQuoteCues(caseNumber).then(() => {
                document.body.style.visibility = "visible";
                // add an element with id "loading-finished" to the page
                let loadingFinished = document.createElement('div');
                loadingFinished.id = "loading-finished";
                document.body.appendChild(loadingFinished);
            });
        }
    });
}

const justiceFormalName = {};

function buildBench(data) {
    let judgesBySeniority = data.heard_by[0].members;
    // put in bench order
    let judges = [];
    // add chief justice
    judges.push(judgesBySeniority[0]);
    // add associate justices
    for (let i = 1; i < judgesBySeniority.length; i++) {
        if (i % 2 == 1) {
            // odd i: add to start
            judges.unshift(judgesBySeniority[i]);
        } else {
            // even i: add to end
            judges.push(judgesBySeniority[i]);
        }
    }
    let bench = document.getElementById('bench');
    for (let i = 0; i < judges.length; i++) {
        let figure = document.createElement('figure');
        figure.id = "justice-" + judges[i].identifier;
        justices.push(judges[i].identifier);
        let img = document.createElement('img');
        let thumbnail_url = judges[i].thumbnail.href;
        // get only the filename
        let filename = thumbnail_url.split('/').pop();
        img.src = "justices/" + filename;
        figure.appendChild(img);
        let caption = document.createElement('figcaption');
        justiceFormalName[judges[i].identifier] = "Justice " + judges[i].last_name;
        if (judges[i].roles[0].role_title == "Chief Justice of the United States") {
            caption.innerHTML = "&nbsp;&nbsp;Chief Justice " + judges[i].last_name;
            justiceFormalName[judges[i].identifier] = "Chief Justice " + judges[i].last_name;
        } else if (judges[i].last_name == "Sotomayor") {
            caption.innerHTML = "&nbsp;&nbsp;&nbsp;Justice " + judges[i].last_name; // better centering
        } else {
            caption.innerHTML = "Justice " + judges[i].last_name;
        }
        if (judges[i].recused === true) {
            figure.classList.add('recused');
            caption.textContent = judges[i].last_name + ' recused';
        }
        figure.appendChild(caption);
        bench.appendChild(figure);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    // get case number from GET parameter (e.g. ?case=19-46)
    let urlParams = new URLSearchParams(window.location.search);
    let caseNumber = urlParams.get('case');
    setUpCase(caseNumber);
});

function showThumbnail(opinionAnnouncement = false) {
    document.querySelector('div.frame').classList.remove('compact');
    document.getElementById('conversation').style.display = "none";
    document.getElementById('transcript').style.display = "none";
    document.getElementById('splash').style.display = "flex";
    document.querySelector(".subtitle").style.visibility = "hidden";
    let caseInfo = document.getElementById('case-info');
    caseInfo.innerHTML = "";

    // rescale title
    const h1 = document.querySelector('div.title h1');
    let fontSize = 110; //px
    h1.style.fontSize = `${fontSize}px`;
    while (h1.scrollWidth > 1750) {
        fontSize -= 0.5;
        h1.style.fontSize = `${fontSize}px`;
    }

    let p = document.createElement('p');
    p.innerHTML = "Oral Argument";
    p.style.fontSize = "253px";
    p.style.fontWeight = "bold";
    p.style.textAlign = "center";
    p.style.marginTop = "0px";
    p.style.marginBottom = "0px";
    caseInfo.appendChild(p);

    if (opinionAnnouncement) {
        subtitle = document.createElement('p');
        subtitle.innerHTML = "and Opinon Announcement";
        subtitle.style.fontSize = "110px";
        subtitle.style.textAlign = "center";
        subtitle.style.marginLeft = "-200px";
        subtitle.style.marginTop = "-40px";
        subtitle.style.marginBottom = "20px";
        caseInfo.appendChild(subtitle);
        withTranscript = document.createElement('p');
        withTranscript.innerHTML = "with transcript!";
        withTranscript.style.position = "absolute";
        withTranscript.style.bottom = "290px";
        withTranscript.style.right = "50px";
        withTranscript.style.fontSize = "60px";
        withTranscript.style.textAlign = "right";
        withTranscript.style.marginLeft = "930px";
        withTranscript.style.marginTop = "-60px";
        withTranscript.style.marginBottom = "20px";
        withTranscript.style.transform = "rotate(-10deg)";
        caseInfo.appendChild(withTranscript);
    } else {
        subtitle = document.createElement('p');
        subtitle.innerHTML = "with transcript";
        subtitle.style.fontSize = "110px";
        subtitle.style.textAlign = "center";
        subtitle.style.marginLeft = "930px";
        subtitle.style.marginTop = "-60px";
        subtitle.style.marginBottom = "20px";
        caseInfo.appendChild(subtitle);
    }

    let imgs = document.createElement('div');
    imgs.className = "thumbnail_advocates";
    for (let advocate of case_data.advocates) {
        let img = document.createElement('img');
        let ident = advocate.advocate.identifier;
        img.src = "advocates/" + ident + ".jpg";
        img.style.objectFit = "cover";
        img.style.width = "300px";
        img.style.height = "300px";
        imgs.appendChild(img);
    }
    imgs.style.display = "flex";
    imgs.style.justifyContent = "center";
    imgs.style.gap = "20px";
    caseInfo.appendChild(imgs);

    if (opinionAnnouncement && case_data.advocates.length > 3) {
        withTranscript.style.bottom = "460px";
        withTranscript.style.right = "130px";
        withTranscript.style.fontSize = "55px";
    }

    let ack = document.querySelector(".acknowledgement");
    ack.style.visibility = "hidden";

    document.addEventListener('keydown', function (event) {
        if (event.key == "ArrowRight") {
            showSplash();
        }
    });
}

function showSplash() {
    document.querySelector('div.frame').classList.remove('compact');
    document.getElementById('conversation').style.display = "none";
    document.getElementById('transcript').style.display = "none";
    document.getElementById('splash').style.display = "flex";
    let caseInfo = document.getElementById('case-info');
    caseInfo.innerHTML = "";
    // resize case title
    const h1 = document.querySelector('div.title h1');
    let fontSize = 60; //px
    h1.style.fontSize = `${fontSize}px`;
    while (h1.scrollWidth > 1750) {
        fontSize -= 0.5;
        h1.style.fontSize = `${fontSize}px`;
    }
    document.querySelector(".subtitle").style.visibility = "visible";
    // put in facts and question
    // check that not null (which happens in emergency petitions)
    if (case_data.facts_of_the_case != null) {
        let h2 = document.createElement('h2');
        h2.innerHTML = "Facts of the case";
        caseInfo.appendChild(h2);
        let facts = document.createElement('div');
        facts.id = "facts-of-the-case";
        facts.className = "oyez-text";
        facts.innerHTML = case_data.facts_of_the_case;
        caseInfo.appendChild(facts);
    }
    h2 = document.createElement('h2');
    h2.innerHTML = "Question";
    caseInfo.appendChild(h2);
    let question = document.createElement('div');
    question.id = "question";
    question.className = "oyez-text";
    question.innerHTML = case_data.question;
    caseInfo.appendChild(question);
    let ack = document.querySelector(".acknowledgement");
    ack.style.visibility = "visible";
    adjustFontSize();
    document.addEventListener('keydown', function (event) {
        if (event.key == "ArrowRight") {
            setUpSection(0);
        }
    });
}

function showConclusion() {
    // check if case_data has conclusion
    if (case_data.conclusion == null) {
        // no conclusion
        return false;
    }
    for (let element of document.querySelectorAll('.active-speaker')) {
        element.classList.remove('active-speaker');
    }
    document.getElementById('conversation').style.display = "none";
    document.getElementById('transcript').style.display = "none";
    document.getElementById('splash').style.display = "flex";
    let caseInfo = document.getElementById('case-info');
    caseInfo.innerHTML = "";
    // if conclusion contains "Yes." or "No.", also display the question
    let question = case_data.question;
    if (case_data.conclusion.includes("Yes.") || case_data.conclusion.includes("No.")) {
        let qH2 = document.createElement('h2');
        qH2.innerHTML = "Question";
        caseInfo.appendChild(qH2);
        let qDiv = document.createElement('div');
        qDiv.id = "question";
        qDiv.className = "oyez-text";
        qDiv.innerHTML = question;
        caseInfo.appendChild(qDiv);
    }
    // put in conclusion
    let h2 = document.createElement('h2');
    h2.innerHTML = "Conclusion";
    caseInfo.appendChild(h2);
    let conclusion = document.createElement('div');
    conclusion.id = "conclusion";
    conclusion.className = "oyez-text";
    conclusion.innerHTML = case_data.conclusion;
    caseInfo.appendChild(conclusion);
    adjustFontSize();
    return true;
}

function announceOpinionAnnouncements() {
    document.getElementById('conversation').style.display = "none";
    document.getElementById('transcript').style.display = "none";
    document.getElementById('splash').style.display = "flex";
    let caseInfo = document.getElementById('case-info');
    caseInfo.innerHTML = "";
    let h2 = document.createElement('h2');
    h2.innerHTML = "Opinion Announcement";
    h2.style.fontSize = "100px";
    h2.style.marginTop = "250px";
    caseInfo.appendChild(h2);
    document.addEventListener('keydown', function (event) {
        if (event.key == "ArrowRight") {
            setUpSection(0);
        }
    });
}

function announceNextArgument(argumentTitle) {
    document.getElementById('conversation').style.display = "none";
    document.getElementById('transcript').style.display = "none";
    document.getElementById('splash').style.display = "flex";
    let caseInfo = document.getElementById('case-info');
    caseInfo.innerHTML = "";
    let h2 = document.createElement('h2');
    h2.innerHTML = argumentTitle;
    h2.style.fontSize = "80px";
    h2.style.marginTop = "250px";
    h2.style.textAlign = "center";
    caseInfo.appendChild(h2);
}

function adjustFontSize() {
    const splash = document.getElementById('splash');
    const texts = document.querySelectorAll('.oyez-text');
    let fontSize = 33;
    const h2s = document.querySelectorAll('div.splash h2');
    let h2FontSize = 40;

    // Set the initial font size
    texts.forEach(text => {
        text.style.fontSize = `${fontSize}px`;
    });
    h2s.forEach(h2 => {
        h2.style.fontSize = `${h2FontSize}px`;
    });

    // Check if overflow exists and reduce font size accordingly
    while (splash.scrollHeight > splash.clientHeight && fontSize > 0) {
        fontSize -= 0.5; // You can adjust this decrement value to make the adjustment finer or coarser
        texts.forEach(text => {
            text.style.fontSize = `${fontSize}px`;
        });
        h2FontSize -= 0.5;
        h2s.forEach(h2 => {
            h2.style.fontSize = `${h2FontSize}px`;
        });
    }
    document.querySelector(".acknowledgement").style.fontSize = `${Math.min(fontSize, 25)}px`;
}

function loadTranscript(section) {
    let transcript = document.getElementById('transcript');
    transcript.innerHTML = "";
    let turnNumber = 0;
    for (let turn of section.turns) {
        let turnDiv = document.createElement('div');
        turnDiv.className = "turn";
        let turnSpeaker = document.createElement('div');
        turnSpeaker.className = "turn-speaker";
        let speakerImg = document.createElement('img');
        if (!turn.speaker) {
            console.error(`Turn speaker is ${turn.speaker}`);
        }
        if (justices.includes(turn.speaker.identifier)) {
            speakerImg.src = document.getElementById('justice-' + turn.speaker.identifier).firstChild.src;
        } else {
            speakerImg.src = "advocates/" + turn.speaker.identifier + ".jpg";
        }
        turnSpeaker.appendChild(speakerImg);
        turnDiv.appendChild(turnSpeaker);
        let textBlocks = document.createElement('div');
        let speakerLabel = document.createElement('div');
        if (justices.includes(turn.speaker.identifier)) {
            speakerLabel.innerHTML = justiceFormalName[turn.speaker.identifier];
        } else {
            speakerLabel.innerHTML = turn.speaker.name;
        }    
        speakerLabel.className = "speaker-label";
        textBlocks.appendChild(speakerLabel);
        textBlocks.className = "text-blocks";
        if (justices.includes(turn.speaker.identifier)) {
            textBlocks.classList.add("text-blocks-justice");
        }
        let textBlockNumber = 0;
        for (let block of turn.text_blocks) {
            let p = document.createElement('p');
            p.innerHTML = block.text;
            p.dataset.turn = turnNumber;
            p.dataset.textBlock = textBlockNumber;
            textBlocks.appendChild(p);
            textBlockNumber++;
        }
        turnDiv.appendChild(textBlocks);
        transcript.appendChild(turnDiv);
        turnNumber++;
    }
}

function buildAdvocateProfile(sectionNumber) {
    let sectionInfo = interactions_data.sections[sectionNumber];
    document.getElementById('advocate-name').innerHTML = "<span>" + sectionInfo.advocateName + "</span>";
    document.getElementById('advocate-description').innerHTML = sectionInfo.advocateDescription;
    document.getElementById('advocate-img').src = "advocates/" + sectionInfo.advocateIdentifier + ".jpg";
    // show interactions
    let container = document.getElementById('justice-interactions');
    container.innerHTML = "";
    let interactionNumber = 0;
    for (let interaction of sectionInfo.interactions) {
        let div = document.createElement('div');
        div.id = "interaction-" + interactionNumber;
        div.className = "interaction";
        let img = document.createElement('img');
        img.src = document.getElementById('justice-' + interaction.justice).firstChild.src;
        div.appendChild(img);
        let numberDisplay = document.createElement('div');
        numberDisplay.innerHTML = interactionNumber + 1;
        numberDisplay.className = "interaction-number";
        div.appendChild(numberDisplay);
        container.appendChild(div);
        interactionNumber++;
    }
    sizeInteractionTiles(container, sectionInfo.interactions.length);
}

// Choose the tile size: the fewest rows that keep tiles at least TILE_MIN_WIDTH wide,
// with the tiles spread evenly over the rows (so the last row is never nearly empty).
const TILE_MAX_WIDTH = 100;
const TILE_MIN_WIDTH = 75;
const TILE_GAP = 5;

function sizeInteractionTiles(container, count) {
    container.classList.remove('fixed-columns');
    container.style.removeProperty('--tile');
    container.style.removeProperty('--cols');
    if (count == 0 || announcementMode) {
        return;
    }
    let conversation = document.getElementById('conversation');
    let availableWidth = conversation.clientWidth - 40;
    let availableHeight = conversation.clientHeight - container.offsetTop - 20;
    let best = null;
    for (let rows = 1; rows <= count; rows++) {
        let columns = Math.ceil(count / rows);
        let width = Math.min(TILE_MAX_WIDTH, (availableWidth - (columns - 1) * TILE_GAP) / columns);
        width = Math.min(width, (availableHeight / rows - TILE_GAP) / 1.4);
        if (width >= TILE_MIN_WIDTH) {
            best = { columns: columns, width: width };
            break;
        }
        if (!best || width > best.width) {
            best = { columns: columns, width: width };
        }
    }
    container.style.setProperty('--tile', best.width / 100);
    container.style.setProperty('--cols', best.columns);
    container.classList.add('fixed-columns');
}

function loadOpinionAnnouncement(opinionNumber) {
    let announcement = announcements[opinionNumber];
    sectionsObject = announcement.transcript.sections;
    document.getElementById('conversation').style.display = "none";
    document.querySelector("div.main").style.justifyContent = "center";
    document.querySelector("div.transcript").style.borderLeft = "none";
    document.querySelector("div.transcript").style.width = "100%";
    document.querySelector("div.transcript").style.paddingLeft = "80px";
    document.querySelector("div.transcript").style.paddingRight = "160px";
    announcementMode = true;
    mp3length = parseInt(interactions_data.announcements[opinionNumber]["mp3_length"]);
    setUpSection(0);
}

function loadNextOpinionAnnouncement() {
    currentOpinion++;
    loadOpinionAnnouncement(currentOpinion);
}

// Offline capture supplies audio-clock progress; no wall-clock timers or CSS animation.
function setSubscribeReminderProgress(elapsed, duration = 8) {
    const reminder = document.querySelector('.subscribe-suggestion');
    const visible = !announcementMode && elapsed >= 0 && elapsed < duration;
    const fade = Math.max(0, Math.min(1, elapsed / .4, (duration - elapsed) / .4));
    reminder.style.display = visible ? 'block' : 'none';
    reminder.style.opacity = visible ? String(easeInOut(fade)) : '0';
    reminder.style.transform = `translateY(${-12 * (1 - easeInOut(fade))}px)`;
}

function showSubscibeSuggestion() {
    let subscribe = document.querySelector('.subscribe-suggestion');
    subscribe.style.display = "block";
}

function hideSubscibeSuggestion() {
    let subscribe = document.querySelector('.subscribe-suggestion');
    subscribe.style.display = "none";
}

function setUpSection(sectionNumber) {
    // compact header during the argument
    let frame = document.querySelector('div.frame');
    frame.classList.add('compact');
    frame.style.setProperty('--main-height', (1080 - document.querySelector('div.header').offsetHeight) + "px");
    activeQuoteCue = null;
    document.getElementById('justice-interactions').classList.remove('fixed-columns');
    setQuoteProgress(0);
    // go to section view
    document.getElementById('transcript').style.display = "block";
    document.getElementById('splash').style.display = "none";
    // show advocate
    if (!announcementMode) {
        document.getElementById('conversation').style.display = "flex";
        buildAdvocateProfile(sectionNumber);
    }
    // load transcript
    let section = sectionsObject[sectionNumber];
    loadTranscript(section);
    // scroll to top of transcript
    transcript.scrollTop = 0;
    for (let element of document.querySelectorAll('.active-speaker')) {
        element.classList.remove('active-speaker');
    }
    currentSection = sectionNumber;
    currentTurn = 0;
    currentTextBlock = -1;
    currentInteraction = -1;
    reachedLastTextBlock = false;
    document.addEventListener('keydown', function (event) {
        if (event.key == "ArrowRight") {
            nextTextBlock(true); // true = manually triggered
        }
    });
}

function nextTextBlock(manuallyTriggered = false) {
    if (reachedLastTextBlock) {
        return;
    }
    let section = sectionsObject[currentSection];
    let turn = section.turns[currentTurn];
    // remove current-text class from all text blocks
    for (let textBlock of document.querySelectorAll('.current-text')) {
        textBlock.classList.remove('current-text');
    }
    for (let element of document.querySelectorAll('.active-speaker')) {
        element.classList.remove('active-speaker');
    }
    let textBlocks;
    let textBlock;
    if (currentTextBlock + 1 < turn.text_blocks.length) {
        // stay on same turn
        currentTextBlock++;
    } else {
        // go to next turn
        currentTurn++;
        turn = section.turns[currentTurn];
        currentTextBlock = 0;
        // check if turn brought us to new interaction
        if (!announcementMode) {
            for (let [index, interaction] of interactions_data.sections[currentSection].interactions.entries()) {
                if (interaction.start == currentTurn) {
                    currentInteraction = index;
                }
            }
        }
    }
    // update current speaker
    let speaker = turn.speaker;
    if (justices.includes(speaker.identifier)) {
        const justiceBlock = document.getElementById('justice-' + speaker.identifier);
        justiceBlock.classList.add('active-speaker');
    } else {
        document.getElementById('advocate').classList.add('active-speaker');
    }
    // update current interaction
    if (!announcementMode && currentInteraction != -1) {
        let interactionImg = document.getElementById('interaction-' + currentInteraction);
        interactionImg.classList.add('active-speaker');
        // compute percent of turn that has passed
        let interaction = interactions_data.sections[currentSection].interactions[currentInteraction];
        let interactionDuration = interaction.endTime - interaction.startTime;
        let startDelta = turn.text_blocks[currentTextBlock].start - interaction.startTime;
        let percent = startDelta / interactionDuration * 100;
        interactionImg.children[0].style.setProperty('--percent', percent + "%");
    }
    textBlocks = document.querySelectorAll('.text-blocks')[currentTurn];
    textBlock = textBlocks.children[currentTextBlock + 1]; // +1 because first child is speaker label
    textBlock.classList.add('current-text');
    let textBlockRect = textBlock.getBoundingClientRect();
    let transcript = document.getElementById('transcript');
    let transcriptRect = transcript.getBoundingClientRect();
    let amountToScroll = 0;
    let scrollBuffer = announcementMode ? 350 : 450;
    if (textBlockRect.bottom > transcriptRect.bottom - scrollBuffer) {
        amountToScroll = textBlockRect.bottom - transcriptRect.bottom + scrollBuffer;
    }
    // check if reachedLastTextBlock
    if (currentTurn == section.turns.length - 1 && currentTextBlock == turn.text_blocks.length - 1) {
        reachedLastTextBlock = true;
    }
    // is there another section?
    let totalSections = sectionsObject.length;
    let goToNextSection = currentSection + 1 < totalSections && reachedLastTextBlock;
    let duration = turn.text_blocks[currentTextBlock].stop - turn.text_blocks[currentTextBlock].start;
    let frameInfo = [];
    if (reachedLastTextBlock && !goToNextSection && duration < 0.5) {
        // last turn in oyez is missing "stop"
        duration = mp3length - turn.text_blocks[currentTextBlock].start;
        transcript.scrollTop += amountToScroll;
    } else if (duration < 0.6 || amountToScroll <= 30 || manuallyTriggered) {
        // scroll immediately
        transcript.scrollTop += amountToScroll;
    } else {
        // scroll over 4 frames
        transcript.scrollTop += 0.2 * amountToScroll;
        frameInfo = [[0.3 * amountToScroll, 0.05], [0.3 * amountToScroll / 3, 0.05], [0.2 * amountToScroll, 0.05], [0, duration - 0.2]];
        duration = 0.05;
    }
    // quote card: show/hide when the current text block enters/leaves a cue
    let blockTotal = duration;
    for (let [, d] of frameInfo) {
        blockTotal += d;
    }
    let quoteSteps = updateQuoteCue(turn.text_blocks[currentTextBlock].start, manuallyTriggered, blockTotal);
    if (quoteSteps.length > 0) {
        [duration, frameInfo] = mergeQuoteFrames(duration, frameInfo, quoteSteps);
    }
    return { duration: duration, lastTurn: reachedLastTextBlock, goToNextSection: goToNextSection, frameInfo: frameInfo, currentSection: currentSection };
}

function goToNextSection() {
    setUpSection(currentSection + 1);
}

function scrollTranscript(amount) {
    let transcript = document.getElementById('transcript');
    transcript.scrollTop += amount;
}
// ---------------------------------------------------------------------------
// Quote mockup
// ---------------------------------------------------------------------------

function loadQuoteCues(caseNumber) {
    let fonts = ['400', '600', '700', 'italic 400', 'italic 600'].map(style => document.fonts.load(`${style} 20px myriad-pro`));
    return Promise.all(fonts).then(() => fetch(`http://localhost:8002/json/${caseNumber}-cards.json`))
        .then(response => response.ok ? response.json() : { cues: [] })
        .then(data => {
            quoteCues = data.cues;
            let images = quoteCues.filter(cue => cue.image).map(cue => new Promise(resolve => {
                let img = new Image();
                img.onload = () => { cue.imageSize = [img.naturalWidth, img.naturalHeight]; resolve(); };
                img.onerror = resolve;
                img.src = cue.image;
            }));
            return Promise.all(images).then(() => quoteCues.some(cue => cue.map) &&
                fetch('http://localhost:8002/maps/circuits.svg').then(r => r.text()).then(text => { circuitMapSvg = text; }));
        })
        .catch(() => { quoteCues = []; });
}

function quoteCueAt(time) {
    // cue times come from transcript text blocks, so compare with a small tolerance
    for (let cue of quoteCues) {
        if (time >= cue.start - 0.05 && time < cue.end - 0.05) {
            return cue;
        }
    }
    return null;
}

function lerp(a, b, t) {
    return a + (b - a) * t;
}

// Mark the phrases a card refers to (cue.highlight) in the transcript blocks it covers.
const HIGHLIGHT_LOOKBACK = 60; // seconds of transcript before a card in which its phrases are also marked

// The previous card's marks become "old" and fade out while the new ones fade in.
function highlightTranscript(cue) {
    let transcript = document.getElementById('transcript');
    for (let span of transcript.querySelectorAll('span.card-reference.old')) {
        span.replaceWith(document.createTextNode(span.textContent));
    }
    for (let span of transcript.querySelectorAll('span.card-reference')) {
        span.classList.add('old');
    }
    transcript.normalize();
    transcript.style.setProperty('--reference-old', 1);
    transcript.style.setProperty('--reference-new', 0);
    if (!cue || !cue.highlight || !cue.highlight.length) {
        return;
    }
    let escape = phrase => phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
    let pattern = new RegExp(`(${cue.highlight.map(escape).join('|')})`, 'gi');
    let turns = sectionsObject[currentSection].turns;
    for (let p of transcript.querySelectorAll('div.text-blocks p')) {
        let block = turns[p.dataset.turn].text_blocks[p.dataset.textBlock];
        // also mark earlier mentions still on screen (or from cue.highlight_from, if the card sets it)
        let from = cue.highlight_from ?? cue.start - HIGHLIGHT_LOOKBACK;
        if (block.start < from - 0.05 || block.start >= cue.end) {
            continue;
        }
        let walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
        let nodes = [];
        while (walker.nextNode()) {
            nodes.push(walker.currentNode);
        }
        for (let node of nodes) {
            let parts = node.textContent.split(pattern);
            if (parts.length == 1) {
                continue;
            }
            let fragment = document.createDocumentFragment();
            parts.forEach((part, i) => {
                if (i % 2 == 1) {
                    let span = document.createElement('span');
                    span.className = 'card-reference new';
                    span.textContent = part;
                    fragment.appendChild(span);
                } else if (part) {
                    fragment.appendChild(document.createTextNode(part));
                }
            });
            node.replaceWith(fragment);
        }
    }
}

let quoteSwap = null; // {from, to} card snapshots while one card replaces another

function cardSnapshot(id) {
    let conversation = document.getElementById('conversation');
    return {
        id: id,
        html: document.getElementById('quote-card').innerHTML,
        height: parseFloat(conversation.style.getPropertyValue('--card-height')),
        squeeze: parseFloat(conversation.style.getPropertyValue('--squeeze') || 1)
    };
}

function showCardSnapshot(snapshot) {
    let card = document.getElementById('quote-card');
    if (card.dataset.showing != snapshot.id) {
        card.innerHTML = snapshot.html;
        card.dataset.showing = snapshot.id;
    }
    document.getElementById('conversation').style.setProperty('--card-height', snapshot.height + "px");
}

function setReferenceOpacity(oldOpacity, newOpacity) {
    let transcript = document.getElementById('transcript');
    transcript.style.setProperty('--reference-old', oldOpacity);
    transcript.style.setProperty('--reference-new', newOpacity);
}

// t: linear progress of a swap. The new card slides up over the old one, which recedes and fades;
// the tiles move between the two cards' squeeze levels and the transcript marks cross-fade.
function setSwapProgress(t) {
    let conversation = document.getElementById('conversation');
    let card = document.getElementById('quote-card');
    let { from, to } = quoteSwap;
    setReferenceOpacity(1 - easeInOut(t), easeInOut(t));
    conversation.style.setProperty('--q', 1);
    conversation.style.setProperty('--squeeze', lerp(from.squeeze, to.squeeze, easeInOut(t)));
    card.classList.add('visible');
    let under = document.getElementById('quote-card-under');
    if (t < 1 && !under) {
        // the old card stays where it was, underneath
        under = document.createElement('div');
        under.id = 'quote-card-under';
        under.className = card.className;
        under.innerHTML = from.html.replace(/ id="[^"]*"/g, "");
        under.style.height = from.height + "px";
        card.parentNode.insertBefore(under, card);
    }
    showCardSnapshot(to);
    let e = easeInOut(t);
    placeCard((1 - e) * (to.height + 40));
    if (under) {
        if (t >= 1) {
            under.remove();
            return;
        }
        // recede: slightly smaller, lifted and fading as the new card covers it
        under.style.transform = `translateY(${-10 * e}px) scale(${1 - 0.04 * e})`;
        under.style.opacity = String(1 - 0.8 * e);
    }
}

function placeCard(slide) {
    // slide in from the bottom, but never above the tiles
    let conversation = document.getElementById('conversation');
    let card = document.getElementById('quote-card');
    let container = document.getElementById('justice-interactions');
    let cardHeight = parseFloat(conversation.style.getPropertyValue('--card-height'));
    let restingTop = conversation.clientHeight - 18 - cardHeight;
    let top = conversation.getBoundingClientRect().top;
    let tilesBottom = container.getBoundingClientRect().bottom - top;
    for (let tile of container.children) {
        tilesBottom = Math.max(tilesBottom, tile.getBoundingClientRect().bottom - top);
    }
    card.style.transform = `translateY(${Math.max(slide, tilesBottom + 20 - restingTop)}px)`;
}

// p: linear progress of the transition, 0 (no quote) to 1 (quote fully shown)
function setQuoteProgress(p) {
    if (p && typeof p == 'object') {
        setSwapProgress(p.swap);
        return;
    }
    let conversation = document.getElementById('conversation');
    let card = document.getElementById('quote-card');
    let q = easeInOut(p);
    conversation.style.setProperty('--q', q);
    // marks of the shown card follow the card in; marks of a leaving card follow it out
    setReferenceOpacity(activeQuoteCue ? 0 : q, activeQuoteCue ? q : 0);
    card.classList.toggle('visible', p > 0);
    if (p > 0) {
        let cardHeight = parseFloat(conversation.style.getPropertyValue('--card-height'));
        placeCard((1 - q) * (cardHeight + 30));
    }
}

function easeInOut(x) {
    // sine ease: gentle acceleration and deceleration
    return -(Math.cos(Math.PI * x) - 1) / 2;
}

// Returns the progress values of the frames that follow the current one.
// The first step is applied immediately.
function updateQuoteCue(time, instant, blockDuration) {
    if (announcementMode) {
        return [];
    }
    let cue = quoteCueAt(time);
    if (cue === activeQuoteCue) {
        return [];
    }
    let previous = activeQuoteCue;
    let swap = previous && cue;
    if (!instant && blockDuration < (QUOTE_TRANSITION_FRAMES + 1) * QUOTE_FRAME_DURATION) {
        // text block too short to animate: try again at the next text block
        return [];
    }
    activeQuoteCue = cue;
    highlightTranscript(cue);
    if (swap && !instant) {
        // one card replaces another: slide the old one out, the new one in
        let from = cardSnapshot(previous.id);
        fillQuoteCard(cue);
        quoteSwap = { from: from, to: cardSnapshot(cue.id) };
        showCardSnapshot(from);
        let steps = [];
        for (let i = 1; i <= QUOTE_TRANSITION_FRAMES; i++) {
            steps.push({ swap: i / QUOTE_TRANSITION_FRAMES });
        }
        setQuoteProgress(steps[0]);
        return steps.slice(1);
    }
    quoteSwap = null;
    if (cue) {
        fillQuoteCard(cue);
    }
    if (instant) {
        setQuoteProgress(cue ? 1 : 0);
        return [];
    }
    let steps = [];
    for (let i = 1; i <= QUOTE_TRANSITION_FRAMES; i++) {
        // linear progress; easing is applied per element in setQuoteProgress
        let x = i / QUOTE_TRANSITION_FRAMES;
        steps.push(cue ? x : 1 - x);
    }
    setQuoteProgress(steps[0]);
    return steps.slice(1);
}

// Combine the transcript scroll frames with the quote animation frames.
// frameInfo entries become [scrollAmount, duration, quoteProgress].
function mergeQuoteFrames(duration, frameInfo, quoteSteps) {
    let total = duration;
    for (let [, d] of frameInfo) {
        total += d;
    }
    let animationLength = (quoteSteps.length + 1) * QUOTE_FRAME_DURATION;
    if (total < animationLength + QUOTE_FRAME_DURATION) {
        // text block too short to animate: jump to the end state
        setQuoteProgress(quoteSteps[quoteSteps.length - 1]);
        return [duration, frameInfo];
    }
    let round = x => Math.round(x * 1000) / 1000;
    let events = new Map(); // time -> [scroll, q]
    let event = t => {
        t = round(t);
        if (!events.has(t)) {
            events.set(t, [0, undefined]);
        }
        return events.get(t);
    };
    // scroll steps are snapped to the quote animation's frame grid
    let t = duration;
    for (let [amount, d] of frameInfo) {
        let snapped = t < animationLength ? Math.round(t / QUOTE_FRAME_DURATION) * QUOTE_FRAME_DURATION : t;
        event(snapped)[0] += amount;
        t += d;
    }
    quoteSteps.forEach((q, i) => { event((i + 1) * QUOTE_FRAME_DURATION)[1] = q; });
    let times = [...events.keys()].filter(time => time < total).sort((a, b) => a - b);
    let newFrameInfo = [];
    let lastQ = undefined;
    for (let i = 0; i < times.length; i++) {
        let [amount, q] = events.get(times[i]);
        if (q !== undefined) {
            lastQ = q;
        }
        let next = i + 1 < times.length ? times[i + 1] : total;
        newFrameInfo.push([amount, round(next - times[i]), lastQ]);
    }
    return [times[0], newFrameInfo];
}

function fillQuoteCard(cue) {
    document.getElementById('quote-card-under')?.remove();
    document.getElementById('quote-card').dataset.showing = cue.id;
    document.getElementById('quote-kind').innerHTML = cue.label ?? cue.kind; // case cards have no label
    document.getElementById('quote-heading').innerHTML = cue.heading ?? "";
    document.getElementById('quote-source').innerHTML = (cue.source ?? "") + (cue.date ? " &middot; filed " + cue.date : "");
    let conversation = document.getElementById('conversation');
    let card = document.getElementById('quote-card');
    // measure the free space with the sidebar fully squeezed
    let oldQ = conversation.style.getPropertyValue('--q');
    let wasVisible = card.classList.contains('visible');
    conversation.style.setProperty('--q', 1);
    conversation.style.setProperty('--squeeze', 1);
    card.classList.add('visible');
    let interactions = document.getElementById('justice-interactions');
    let usedAt = () => interactions.getBoundingClientRect().bottom - conversation.getBoundingClientRect().top;
    let used = usedAt();
    let cardHeight = Math.min(480, conversation.clientHeight - used - 40);
    conversation.style.setProperty('--card-height', cardHeight + "px");
    shrinkToFitWidth(document.querySelector('div.quote-label'), 22, 17);
    shrinkToFitWidth(document.getElementById('quote-source'), 17, 14);
    // fit text: shrink font, then drop context (prefer a larger quote over more context)
    let body = document.getElementById('quote-body');
    // cue.text: primary source text (statute) with the relevant clause in <mark>;
    // otherwise a filing excerpt: grey context around the highlighted quote
    let variants = cue.text ? [[true, true, 17]] : [[true, true, 21], [true, false, 21], [false, false, 17]];
    for (let [withBefore, withAfter, minimumSize] of variants) {
        body.innerHTML = cardBodyHtml(cue, withBefore, withAfter);
        if (cue.map) {
            decorateMap(body, cue);
        }
        body.classList.toggle('quote-only', !cue.text && !(withBefore && cue.before) && !(withAfter && cue.after));
        let fontSize = 23;
        body.style.fontSize = fontSize + "px";
        while (body.scrollHeight > body.clientHeight && fontSize > minimumSize) {
            fontSize -= 0.5;
            body.style.fontSize = fontSize + "px";
        }
        if (body.scrollHeight <= body.clientHeight) {
            break;
        }
    }
    // short texts: shrink the card to its content (it stays anchored at the bottom)
    let range = document.createRange();
    range.selectNodeContents(body);
    let spare = body.getBoundingClientRect().bottom - range.getBoundingClientRect().bottom - parseFloat(getComputedStyle(body).paddingBottom);
    if (spare > 0) {
        cardHeight -= spare;
        conversation.style.setProperty('--card-height', cardHeight + "px");
    }
    // squeeze the sidebar only as much as this card needs
    let available = conversation.clientHeight - cardHeight - 40;
    let low = 0, high = 1;
    for (let i = 0; i < 12; i++) {
        let mid = (low + high) / 2;
        conversation.style.setProperty('--squeeze', mid);
        if (usedAt() <= available) {
            high = mid;
        } else {
            low = mid;
        }
    }
    conversation.style.setProperty('--squeeze', high);
    card.classList.toggle('visible', wasVisible);
    setQuoteProgress(parseFloat(oldQ || 0));
}

function shrinkToFitWidth(element, maximumSize, minimumSize) {
    let fontSize = maximumSize;
    element.style.fontSize = fontSize + "px";
    while (element.scrollWidth > element.clientWidth && fontSize > minimumSize) {
        fontSize -= 0.5;
        element.style.fontSize = fontSize + "px";
    }
}

function cardBodyHtml(cue, withBefore, withAfter) {
    if (cue.case) {
        return caseBodyHtml(cue);
    }
    if (cue.glossary) {
        return `<div class="glossary-term"><b>${cue.glossary.term}</b> <span class="glossary-expansion">${cue.glossary.expansion}</span></div>` +
            `<div class="glossary-text">${cue.text}</div>`;
    }
    if (cue.compare) {
        return `<div class="compare">` + cue.compare.map(column =>
            `<div class="compare-column"><div class="compare-title">${column.title}</div>` +
            `<div class="compare-cite">${column.cite ?? ""}</div><div class="compare-text">${column.text}</div></div>`).join("") + `</div>`;
    }
    if (cue.timeline) {
        return `<div class="timeline">` + cue.timeline.events.map((event, i) =>
            `<div class="timeline-event${i == cue.timeline.current ? " current" : ""}${event.gap ? " after-gap" : ""}">` +
            `<div class="timeline-date">${event.date}</div><div class="timeline-track"><div class="timeline-dot"></div></div>` +
            `<div class="timeline-label">${event.label}</div></div>`).join("") + `</div>`;
    }
    if (cue.image) {
        let [w, h] = cue.imageSize || [4, 3];
        return `<img class="exhibit" src="${cue.image}" width="${w}" height="${h}">`;
    }
    if (cue.map) {
        return `<div class="map-wrap"><div class="map-svg">${circuitMapSvg}</div><div class="map-legend">` +
            cue.map.groups.map(group => `<div class="map-legend-item"><span class="swatch" style="background: ${group.color}"></span>` +
                `<span><b>${group.label}</b><br>${circuitList(group.circuits)}</span></div>`).join("") +
            (cue.map.below ? `<div class="map-legend-item"><span class="swatch below"></span><span>Decision under review<br>${circuitName(cue.map.below)}</span></div>` : "") +
            `</div></div>`;
    }
    if (cue.text) {
        return cue.text;
    }
    return quoteBodyHtml(cue, withBefore, withAfter);
}

const MAP_LABEL_OFFSETS = { "11": [3, -96] }; // Florida's box centre is in the Gulf: use Georgia
const MAP_ROTATION = -6; // degrees, counterclockwise

function circuitList(circuits) {
    let names = circuits.map(c => circuitName(c).replace(" Cir.", ""));
    return names.slice(0, -1).join(", ") + (names.length > 1 ? " and " : "") + names[names.length - 1] + (names.length > 1 ? " Circuits" : " Circuit");
}

function circuitName(circuit) {
    let ordinals = { "1": "1st", "2": "2nd", "3": "3rd", "11": "11th", "DC": "D.C." };
    return (ordinals[circuit] || circuit + "th") + " Cir.";
}

// Colour the circuits, crop to the contiguous states and number the circuits involved.
function decorateMap(body, cue) {
    let svg = body.querySelector('svg');
    let colours = {};
    for (let group of cue.map.groups) {
        for (let circuit of group.circuits) {
            colours[circuit] = group.color;
        }
    }
    // level the tilted projection a little: the map gets less tall
    let rotated = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    rotated.setAttribute('transform', `rotate(${MAP_ROTATION} 396 306)`);
    let outer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    outer.appendChild(rotated);
    for (let path of [...svg.querySelectorAll('path')]) {
        rotated.appendChild(path);
    }
    svg.appendChild(outer);
    let shapes = [...svg.querySelectorAll('path')];
    let box = null;
    let largest = {};
    for (let shape of shapes) {
        let b = shape.getBBox();
        if (b.y > 500 || b.x < -40) {
            shape.remove(); // Alaska, Hawaii and the territories: keep the map compact
            continue;
        }
        let circuit = shape.dataset.circuit;
        shape.setAttribute('fill', colours[circuit] || 'hsl(43, 22%, 86%)');
        shape.setAttribute('stroke', '#fff');
        shape.setAttribute('stroke-width', '1.2');
        (largest[circuit] ||= []).push([shape, b]);
        box = box ? { x0: Math.min(box.x0, b.x), y0: Math.min(box.y0, b.y), x1: Math.max(box.x1, b.x + b.width), y1: Math.max(box.y1, b.y + b.height) }
            : { x0: b.x, y0: b.y, x1: b.x + b.width, y1: b.y + b.height };
    }
    if (cue.map.below) {
        for (let shape of shapes.filter(s => s.dataset.circuit == cue.map.below && s.isConnected)) {
            shape.setAttribute('stroke', '#222');
            shape.setAttribute('stroke-width', '2.4');
            shape.parentNode.appendChild(shape);
        }
    }
    let angle = MAP_ROTATION * Math.PI / 180;
    let turn = (x, y) => [396 + (x - 396) * Math.cos(angle) - (y - 306) * Math.sin(angle),
                          306 + (x - 396) * Math.sin(angle) + (y - 306) * Math.cos(angle)];
    // tight bounds of the rotated outlines (getBBox of a rotated group bounds the rotated boxes, which is too loose)
    let view = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    for (let shape of shapes.filter(s => s.isConnected)) {
        let length = shape.getTotalLength();
        let samples = Math.max(20, Math.ceil(length / 4));
        for (let i = 0; i <= samples; i++) {
            let point = shape.getPointAtLength(length * i / samples);
            let [x, y] = turn(point.x, point.y);
            view = { x0: Math.min(view.x0, x), y0: Math.min(view.y0, y), x1: Math.max(view.x1, x), y1: Math.max(view.y1, y) };
        }
    }
    svg.setAttribute('viewBox', `${view.x0 - 3} ${view.y0 - 3} ${view.x1 - view.x0 + 6} ${view.y1 - view.y0 + 6}`);
    let offsets = cue.map.labelOffsets || {};
    for (let circuit of Object.keys(colours)) {
        if (!largest[circuit]) {
            continue;
        }
        // label the biggest state of the circuit; fixed corrections where its box centre is off land
        let [, b] = largest[circuit].sort((a, b) => b[1].width * b[1].height - a[1].width * a[1].height)[0];
        let [dx, dy] = offsets[circuit] || MAP_LABEL_OFFSETS[circuit] || [0, 0];
        let [x, y] = turn(b.x + b.width / 2 + dx, b.y + b.height / 2 + dy);
        svg.insertAdjacentHTML('beforeend', `<circle cx="${x}" cy="${y}" r="17" fill="#222"/>` +
            `<text x="${x}" y="${y}" dy="0.36em" text-anchor="middle" font-size="20" font-weight="600" fill="#fff">${circuit}</text>`);
    }
}

function caseBodyHtml(cue) {
    return `<div class="case-name">${cue.case.name}</div>` +
        `<div class="case-details">${cue.case.details}</div>` +
        `<div class="case-holding">${cue.text}</div>`;
}

function quoteBodyHtml(cue, withBefore, withAfter) {
    let html = "";
    if (withBefore && cue.before) {
        html += `<span class="context">${cue.before}</span> `;
    }
    html += `<mark>${cue.quote}</mark>`;
    if (withAfter && cue.after) {
        if (cue.after.startsWith("<sup>")) {
            html += `<p class="footnote">${cue.after}</p>`;
        } else {
            html += ` <span class="context">${cue.after}</span>`;
        }
    }
    return html;
}

// ---------------------------------------------------------------------------
