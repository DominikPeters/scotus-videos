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

function setUpCase(caseNumber) {
    Promise.all([
        fetch(`http://localhost:8002/json/${caseNumber}.json`).then(response => response.json()),
        fetch(`http://localhost:8002/json/${caseNumber}-audio.json`).then(response => response.json()),
        fetch(`http://localhost:8002/json/${caseNumber}-interactions.json`).then(response => response.json())
    ]).then((jsons) => {
        case_data = jsons[0];
        audio_data = jsons[1];
        interactions_data = jsons[2];
        sectionsObject = audio_data.transcript.sections;
        let hasAnnouncements = interactions_data.announcements.length > 0;
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
        document.body.style.visibility = "visible";
        // add an element with id "loading-finished" to the page
        let loadingFinished = document.createElement('div');
        loadingFinished.id = "loading-finished";
        document.body.appendChild(loadingFinished);
    });
}

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
        if (judges[i].roles[0].role_title == "Chief Justice of the United States") {
            caption.innerHTML = "&nbsp;&nbsp;Chief Justice " + judges[i].last_name;
        } else if (judges[i].last_name == "Sotomayor") {
            caption.innerHTML = "&nbsp;&nbsp;&nbsp;Justice " + judges[i].last_name; // better centering
        } else {
            caption.innerHTML = "Justice " + judges[i].last_name;
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
        if (justices.includes(turn.speaker.identifier)) {
            speakerImg.src = document.getElementById('justice-' + turn.speaker.identifier).firstChild.src;
        } else {
            speakerImg.src = "advocates/" + turn.speaker.identifier + ".jpg";
        }
        turnSpeaker.appendChild(speakerImg);
        turnDiv.appendChild(turnSpeaker);
        let textBlocks = document.createElement('div');
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
        let img = document.createElement('img');
        img.src = document.getElementById('justice-' + interaction.justice).firstChild.src;
        img.id = "interaction-" + interactionNumber;
        container.appendChild(img);
        interactionNumber++;
    }
    if (sectionInfo.interactions.length > 21) {
        container.classList.add('small');
    }
    if (sectionInfo.interactions.length > 32) {
        container.classList.add('very-small');
    }
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

function setUpSection(sectionNumber) {
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
            nextTextBlock();
        }
    });
}

function nextTextBlock() {
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
        document.getElementById('justice-' + speaker.identifier).classList.add('active-speaker');
    } else {
        document.getElementById('advocate').classList.add('active-speaker');
    }
    // update current interaction
    if (!announcementMode && currentInteraction != -1) {
        let interactionImg = document.getElementById('interaction-' + currentInteraction);
        interactionImg.classList.add('active-speaker');
    }
    textBlocks = document.querySelectorAll('.text-blocks')[currentTurn];
    textBlock = textBlocks.children[currentTextBlock];
    textBlock.classList.add('current-text');
    let textBlockRect = textBlock.getBoundingClientRect();
    let transcript = document.getElementById('transcript');
    let transcriptRect = transcript.getBoundingClientRect();
    let amountToScroll = 0;
    let scrollBuffer = announcementMode ? 350 : 150;
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
    } else if (duration < 0.6 || amountToScroll <= 30) {
        // scroll immediately
        transcript.scrollTop += amountToScroll;
    } else {
        // scroll over 4 frames
        transcript.scrollTop += 0.2 * amountToScroll;
        frameInfo = [[0.3 * amountToScroll, 0.05], [0.3 * amountToScroll / 3, 0.05], [0.2 * amountToScroll, 0.05], [0, duration - 0.2]];
        duration = 0.05;
    }
    return { duration: duration, lastTurn: reachedLastTextBlock, goToNextSection: goToNextSection, frameInfo: frameInfo };
}

function goToNextSection() {
    setUpSection(currentSection + 1);
}

function scrollTranscript(amount) {
    let transcript = document.getElementById('transcript');
    transcript.scrollTop += amount;
}