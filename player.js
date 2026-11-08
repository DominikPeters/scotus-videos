import {adaptRecording, sharedRecording, defaultCourt} from './player-data.js';
import { VidstackPlayer, VidstackPlayerLayout } from 'https://cdn.vidstack.io/player';

let justices = [];
let case_data;
let audio_data;
let interactions_data;
let sectionsObject;
let announcements;
let announcementMode = false;

let audio = document.querySelector("#player");
window.audio = audio;

let currentSection = -1;
let currentTurn = 0;
let currentTextBlock = -1;
let currentInteraction = -1;
let reachedLastTextBlock = false;
let currentOpinion = -1;

let textBlockStartTimes = [];
let interactionStartTimes = [];

const advocateImageBlobs = {};
const placeholderAdvocateImage = `data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHhtbDpzcGFjZT0icHJlc2VydmUiIHZpZXdCb3g9IjAgMCAyNjQuNTggMjY0LjU4Ij48cGF0aCBmaWxsPSIjZTZlNmU2IiBkPSJNMCAwaDI2NC41OHYyNjQuNThIMHoiLz48cGF0aCBmaWxsPSIjYmJiIiBkPSJNMTMyLjU2IDE3LjkyYy0yLjgtLjEyLTUuNjIuMDYtOC40LjU2bC0xLjg0LjMzYTQzNC42MyA0MzQuNjMgMCAwIDAtMTcuOTkgMy41OCAyNy4wNiAyNy4wNiAwIDAgMC0xMy4yNyA3LjMzbC0yLjEgMi4xYTIwNi45IDIwNi45IDAgMCAwLTEyLjYgMTMuNyA3NC43IDc0LjcgMCAwIDAtNy45MiAxMS40MyAyNC42IDI0LjYgMCAwIDAtMy4wMyAxMS42NXYuNTVjLS4xIDMuOC4yMiA3LjYuOTggMTEuMzFhNzAuOTUgNzAuOTUgMCAwIDEgMS40NiA5LjIybC4xNCAxLjU1Yy4zOCA0LjEzLjg0IDguMjYgMS4zNyAxMi4zOGwuMDUuNGMuNzMgMy4wNC42NCA2LjIyLS4yNSA5LjJhOS4wNCA5LjA0IDAgMCAwLS41IDUuNGwyLjE2IDEwLjA1YzEuMjIgNS45MSAyLjU1IDExLjggNCAxNy42NWExMi42MyAxMi42MyAwIDAgMCAzLjY3IDYuODdjMS42MiAxLjM0IDIuOTQgMyAzLjg5IDQuODdsLjQ0Ljg3YzEuMjYgMi40OCAyLjQ1IDQuOTggMy42IDcuNWwzLjE5IDcuMDRhMjYuMzcgMjYuMzcgMCAwIDEgMi44IDE4LjA2Yy0xLjE1IDQtNS4wMSA4LjkxLTguNjMgMTAuOTZhMjE3OC43MSAyMTc4LjcxIDAgMCAxLTM3LjQ5IDIwLjg1Yy0xNS4zNCA4LjMtMzIuNzIgMjIuMDMtNDYuMjkgMzcuNzl2My40NmgyNjQuNTh2LTIzLjQzYTYyLjQ0IDYyLjQ0IDAgMCAwLTE5LjA4LTE0LjI2bC0xOC40NC04LjgzYTQ1OC4zIDQ1OC4zIDAgMCAwLTQxLjg2LTE4LjkgMTYuMTUgMTYuMTUgMCAwIDEtMTEuMzUtMTAuODMgMTQuNTUgMTQuNTUgMCAwIDEgLjIyLTEwLjQzIDIyLjc2IDIyLjc2IDAgMCAwIDIuNTQtNi42bDEuMTktNS42YTE1LjYzIDE1LjYzIDAgMCAxIDUuODYtMTEuMzYgMTEuMiAxMS4yIDAgMCAwIDUuMi02LjU4bC41Mi0xLjc5YzEuMi00LjA4IDIuMjctOC4yIDMuMjMtMTIuMzVsMS42My03LjA2YTE2LjEyIDE2LjEyIDAgMCAwIC44Ny0xNS41IDYuNyA2LjcgMCAwIDEtMS45LTUuMzNsLjMtMy4zYy40LTQuMjUuOTgtOC41IDEuNzUtMTIuNzFsLjg1LTQuNmEzMi42IDMyLjYgMCAwIDAtLjA4LTE2LjgzIDYzLjQ3IDYzLjQ3IDAgMCAwLTUuMjktMTEuMjdsLTEuMjYtMi4xMmE2NzUuOCA2NzUuOCAwIDAgMS04LjE1LTE0LjA2IDI2LjQyIDI2LjQyIDAgMCAwLTkuNTctMTAgNzEuNiA3MS42IDAgMCAwLTEyLjMxLTUuN2wtMS45NC0uNjlhMjQ1LjggMjQ1LjggMCAwIDAtMTYuNjMtNS4yMiAzNy44MiAzNy44MiAwIDAgMC04LjMyLTEuM3oiLz48L3N2Zz4K`;

// Add scroll buffer variables
let lastManualScroll = 0;
const SCROLL_BUFFER_MS = 3000;

// Add scroll event listener
document.addEventListener('wheel', function (event) {
    lastManualScroll = Date.now();
}, true);

function resetScrollBuffer() {
    lastManualScroll = Date.now() - SCROLL_BUFFER_MS - 1;
}

// when spacebar is pressed, pause or play the audio
document.addEventListener('keydown', function (event) {
    if (event.key == " ") {
        if (audio.paused) {
            audio.play();
        } else {
            audio.pause();
        }
        event.preventDefault();
    }
});

function binarySearch(times, target) {
    // find the index of the last element less than or equal to target
    let left = 0;
    let right = times.length - 1;
    while (left < right) {
        let mid = Math.floor((left + right) / 2);
        if (times[mid] <= target) {
            left = mid + 1;
        } else {
            right = mid;
        }
    }
    return Math.max(0, left - 1);
}

async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to fetch ${url}: ${response.statusText}`);
    }
    return response.json();
}

async function getCaseData(case_metadata, alignedTranscript = null) {
    // Extract advocate information
    const advocates = {};
    for (const adv of case_metadata.advocates) {
        advocates[adv.advocate.name] = {
            name: adv.advocate.name,
            identifier: adv.advocate.identifier,
            description: adv.advocate_description.replace('For ', 'for ').trim(),
            last_name: adv.advocate.last_name
        };
    }
    const all_advocates = new Set(Object.keys(advocates));

    // Extract list of presiding justices
    const justices = {};
    for (const member of case_metadata.heard_by[0].members) {
        justices[member.name] = member;
    }

    // Initialize processed object
    const processed = { sections: {} };

    // A shared Court alignment bypasses Oyez audio/transcript fetching.
    let oral_argument_transcript = alignedTranscript;
    if (!oral_argument_transcript) {
        const oral_argument_url = case_metadata.oral_argument_audio[0].href;
        oral_argument_transcript = await fetchJSON(oral_argument_url);
    }

    // Get MP3 URL
    const mp3_url = oral_argument_transcript.media_file[0].href;

    // Extract transcript sections
    const sections = oral_argument_transcript.transcript.sections;

    let prev_justice = null;
    sections.forEach((section, section_counter) => {
        const turns = section.turns;
        const section_obj = {};
        processed.sections[section_counter] = section_obj;
        section_obj.sectionStartTime = section.start;

        // Determine the headline (name of the first advocate or speaker if no advocate took a turn)
        for (const turn of turns) {
            const speaker_name = turn.speaker.name;
            if (all_advocates.has(speaker_name)) {
                const adv = advocates[speaker_name];
                section_obj.advocateName = adv.name;
                section_obj.advocateIdentifier = adv.identifier;
                section_obj.advocateDescription = adv.description;
                section_obj.advocateLastName = adv.last_name;
                break;
            }
        }

        const interactions = [];
        section_obj.interactions = interactions;

        // List of justices who took turns
        turns.forEach((turn, i) => {
            const current_speaker = turn.speaker.name;

            // Skip certain conditions based on Python logic
            if (current_speaker === "John G. Roberts, Jr." && i === 0) return;

            const text_blocks = turn.text_blocks;
            if (text_blocks.length === 1) {
                const wordCount = text_blocks[0].text.split(/\s+/).length;
                if (wordCount <= 8) return;
                if (current_speaker === "John G. Roberts, Jr." && wordCount <= 15 && i === turns.length - 1) return;
            }

            if (i === turns.length - 1) {
                if (current_speaker === "John G. Roberts, Jr.") return;
            }

            // Check if the current turn is Chief Justice and the next turn is also a justice
            let is_moderation = current_speaker === "John G. Roberts, Jr.";
            if (is_moderation && i < turns.length - 1 && justices.hasOwnProperty(turns[i + 1].speaker.name)) {
                return;
            }

            if (justices.hasOwnProperty(current_speaker) && current_speaker !== prev_justice) {
                interactions.push({
                    justice: justices[current_speaker].identifier,
                    justiceLastName: justices[current_speaker].last_name,
                    start: i,
                    startTime: turn.start
                });
                prev_justice = current_speaker;
            }
        });
    });

    // Format metadata dates
    let argued_time;
    for (const date of case_metadata.timeline) {
        if (date.event === "Argued") {
            argued_time = date.dates[0];
            break;
        }
    }
    const argued_date = new Date(argued_time * 1000).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
    });

    let decided_date = null;
    let is_decided = false;
    for (const date of case_metadata.timeline) {
        if (date.event === "Decided") {
            decided_date = new Date(date.dates[0] * 1000).toLocaleDateString('en-US', {
                month: 'short', day: 'numeric', year: 'numeric'
            });
            is_decided = true;
            break;
        }
    }

    processed.dates = `Argued on ${argued_date}.` + (is_decided ? `\nDecided on ${decided_date}.` : '');

    const docket_number = case_metadata.docket_number;
    const wikipedia_url = `https://en.wikipedia.org/wiki/${case_metadata.name.replace(/ /g, '_')}`;

    let docket_text = "";
    try {
        if (parseInt(case_metadata.term) >= 2001) {
            docket_text = `Docket: https://www.supremecourt.gov/docket/docketfiles/html/public/${docket_number}.html\n`;
        }
    } catch (e) {
        // ignore parse errors
    }

    let parties_text = `*${case_metadata.first_party_label}:* ${case_metadata.first_party}\n`;
    if (case_metadata.second_party) {
        parties_text += `*${case_metadata.second_party_label}:* ${case_metadata.second_party}`;
    }

    const advocates_list = Object.values(advocates)
        .map(adv => `- ${adv.name} (${adv.description})`)
        .join('\n');

    let conclusion_text = "";
    if (is_decided) {
        conclusion_text = `\n*Conclusion*\n${case_metadata.conclusion}`;
    }

    let facts = "";
    if (case_metadata.facts_of_the_case) {
        facts = `\n*Facts of the case (from oyez.org)*\n${case_metadata.facts_of_the_case}\n`;
    }

    const description = `Oral argument audio (including transcript) of case 
  [${docket_number}] *${case_metadata.name}*
  argued at the Supreme Court of the United States on ${argued_date}.
  
  *More information about the case:*
  ${wikipedia_url}
  Justia: ${case_metadata.justia_url}
  ${docket_text}Oyez.org: ${case_metadata.href.replace('api.', 'www.')}
  
  This website produced based on information and transcripts on oyez.org, licensed under a CC-BY-NC License (https://creativecommons.org/licenses/by-nc/4.0/).
  Not affiliated with oyez.org or the Supreme Court.
  
  ${processed.dates}
  ${parties_text}
  *Advocates:* 
  ${advocates_list}
  ${facts}*Question*
  ${case_metadata.question || ''}
  ${conclusion_text}`;

    processed.description = description;
    processed.term = case_metadata.term;

    // Return the desired objects
    return {
        case_metadata,
        mp3_url,
        oral_argument_transcript,
        processed
    };
}

// do things we can do before audio is loaded
function earlySetUpCase(case_metadata) {
    document.getElementById('case-name').innerHTML = case_metadata.name;
    document.getElementById('docket-number').innerHTML = "[" + case_metadata.docket_number + "]";
    buildBench(case_metadata);

    let argued_time;
    for (const date of case_metadata.timeline) {
        if (date.event === "Argued") {
            argued_time = date.dates[0];
            break;
        }
    }
    const argued_date = new Date(argued_time * 1000).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
    });
    let decided_date = null;
    let is_decided = false;
    for (const date of case_metadata.timeline) {
        if (date.event === "Decided") {
            decided_date = new Date(date.dates[0] * 1000).toLocaleDateString('en-US', {
                month: 'short', day: 'numeric', year: 'numeric'
            });
            is_decided = true;
            break;
        }
    }

    document.getElementById('subtitle').innerHTML = `Argued on ${argued_date}.` + (is_decided ? `\nDecided on ${decided_date}.` : '');

    document.body.style.visibility = "visible";
}

async function setUpCase(data) {
    case_data = data.case_metadata;
    const caseNumber = case_data.ID;
    audio_data = data.oral_argument_transcript;
    interactions_data = data.processed;
    sectionsObject = audio_data.transcript.sections;
    // let hasAnnouncements = interactions_data.announcements.length > 0;
    // if (hasAnnouncements) {
    //     // for each announcement, load its json (filename: announcement["json"])
    //     Promise.all(interactions_data.announcements.map(announcement =>
    //         fetch(`./json/${announcement.json}`).then(response => response.json()))).then(
    //             (announcementsJsons) => { announcements = announcementsJsons; }
    //         );
    // }
    // number all text blocks
    let textBlockNumber = 0;
    for (let section of sectionsObject) {
        for (let turn of section.turns) {
            for (let block of turn.text_blocks) {
                block.number = textBlockNumber;
                textBlockNumber++;
                textBlockStartTimes.push(block.start);
            }
        }
    }
    // number all interactions
    let interactionNumber = 0;
    for (let sectionNum in interactions_data.sections) {
        let section = interactions_data.sections[sectionNum];
        interactionNumber++; // virtual interaction for start of section
        interactionStartTimes.push(section.sectionStartTime);
        for (let interaction of section.interactions) {
            interaction.number = interactionNumber;
            interactionNumber++;
            interactionStartTimes.push(interaction.startTime);
        }
    }

    for (let i = 0; i < sectionsObject.length; i++) {
        await setUpSection(i);
    }

    // make chapter markers
    const chapters = [];
    for (let [sectionIndex, section] of sectionsObject.entries()) {
        // figure out who is speaking
        let speaker;

        // find first non-justice speaker
        for (const turn of section.turns) {
            if (!justices.includes(turn.speaker.identifier)) {
                speaker = turn.speaker;
                break;
            }
        }

        if (!speaker) {
            throw new Error(`No advocate found in section ${sectionIndex}`);
        }

        // Create chapter marker
        if (sectionIndex === sectionsObject.length - 1 && speaker.name === chapters[0].title) {
            chapters.push({
                text: `Rebuttal: ${speaker.name}`,
                startTime: section.turns[0].start
            });
        } else if (sectionIndex > 0) {
            chapters.push({
                text: speaker.name,
                startTime: section.turns[0].start
            });
        } else {
            chapters.push({
                text: speaker.name,
                startTime: 0  // YouTube requires first chapter to start at 0
            });
        }
    }
    // add end times for each chapter
    for (let i = 0; i < chapters.length - 1; i++) {
        chapters[i].endTime = chapters[i + 1].startTime;
    }
    chapters[chapters.length - 1].endTime = sectionsObject[sectionsObject.length - 1].stop + 10;

    // fetch the mp3
    // fetch(data.mp3_url).then(response => response.blob()).then(async blob => {
    //     let objectURL = URL.createObjectURL(blob);
        let timeUpdateEventName = 'timeupdate';
        try {
            const player = await VidstackPlayer.create({
                target: '#player',
                title: case_data.name,
                // src: { src: objectURL, type: 'audio/mp3' },
                src: { src: data.mp3_url, type: 'audio/mp3' },
                layout: new VidstackPlayerLayout({
                }),
            });
            audio = player;
            player.textTracks.add({
                type: 'json',
                label: 'Chapters',
                kind: 'chapters',
                language: 'en-US',
                default: true,
                content: { cues: chapters }
            });
            timeUpdateEventName = 'time-update';
        } catch (error) {
            console.error(error);
            // audio.src = objectURL;
        }

        player.addEventListener('mouseover', function () {
            resetScrollBuffer();
        });

        player.addEventListener(timeUpdateEventName, function () {
            let index = binarySearch(textBlockStartTimes, audio.currentTime + 0.0001);
            for (let textBlock of document.querySelectorAll('.current-text')) {
                textBlock.classList.remove('current-text');
            }
            let textBlock = document.getElementById('text-block-' + index);
            textBlock.classList.add('current-text');
            if (index != currentTextBlock) {
                // Only scroll if we're outside the scroll buffer period
                if (Date.now() - lastManualScroll > SCROLL_BUFFER_MS) {
                    textBlock.scrollIntoView({ block: "nearest" });
                }
            }
            currentTextBlock = index;
            for (let element of document.querySelectorAll('.active-speaker')) {
                element.classList.remove('active-speaker');
            }
            let interactionIndex = binarySearch(interactionStartTimes, audio.currentTime);
            try {
                let interactionImg = document.getElementById('interaction-' + interactionIndex);
                interactionImg.classList.add('active-speaker');
            } catch (error) {
                // no interaction at this time, because it's a virtual interaction
                // i.e. the start of a section
            }
            if (textBlock.parentElement.classList.contains('text-blocks-advocate')) {
                textBlock.parentElement.parentElement.parentElement.parentElement.querySelector('.advocate').classList.add('active-speaker');
            }
        // });
    });

    document.querySelectorAll('*[data-start]').forEach(element => {
        element.addEventListener('click', function () {
            resetScrollBuffer();
            audio.currentTime = parseFloat(element.dataset.start);
            audio.play();
        });
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
        figure.appendChild(caption);
        bench.appendChild(figure);
    }
}

document.addEventListener('DOMContentLoaded', async function () {
    try {
        const params = new URLSearchParams(window.location.search);
        const match = window.location.pathname.match(/\/web\/([^/]+)\/([^/]+)/);
        const caseNumber = match ? match[1] + '/' + match[2] : params.get('case');
        if (!caseNumber) throw new Error('No case specified');
        const [term, docket] = caseNumber.split('/').map(decodeURIComponent);
        const recordingId = params.get('recording') || '';
        let recording;
        try { recording = await sharedRecording(term, docket, recordingId); }
        catch (error) { if (recordingId) throw error; console.warn('Shared transcript unavailable; trying Oyez', error); }
        if (recordingId && !recording) throw new Error('Requested recording not found');
        let case_metadata, alignedTranscript = null;
        if (recording) {
            const original = await fetch('https://api.oyez.org/cases/' + term + '/' + docket, {signal: AbortSignal.timeout(3000)})
                .then(r => r.ok ? r.json() : null).catch(() => null);
            const adapted = adaptRecording(recording, original, defaultCourt);
            case_metadata = adapted.metadata; alignedTranscript = adapted.transcript;
        } else {
            case_metadata = await fetchJSON('https://api.oyez.org/cases/' + caseNumber);
        }
        case_metadata.docket_number = case_metadata.docket_number.trim();
        earlySetUpCase(case_metadata);
        await setUpCase(await getCaseData(case_metadata, alignedTranscript));
        document.body.dataset.transcriptSource = recording ? 'scotus_ctc' : 'oyez';
        const acknowledgement = document.querySelector('.acknowledgement');
        if (recording && acknowledgement) acknowledgement.textContent =
            (case_metadata.oyez_metadata ? 'Case information: Oyez.org. ' : '') + 'Audio and transcript: Supreme Court of the United States.';
    } catch (error) {
        console.error(error);
        document.body.style.visibility = 'visible';
        document.getElementById('case-name').textContent = 'Unable to load this recording';
        document.getElementById('subtitle').textContent = 'Please reload to try again.';
    }
});


function showSplash() {
    document.getElementById('conversation').style.display = "none";
    document.getElementById('transcript').style.display = "none";
    document.getElementById('splash').style.display = "flex";
    let caseInfo = document.getElementById('case-info');
    caseInfo.innerHTML = "";
    // resize case title
    const h1 = document.querySelector('div.title h1');
    let fontSize = 50; //px
    h1.style.fontSize = `${fontSize}px`;
    while (h1.scrollWidth > screen.width - 100) {
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
    let h2 = document.createElement('h2');
    h2.innerHTML = "Question";
    caseInfo.appendChild(h2);
    let question = document.createElement('div');
    question.id = "question";
    question.className = "oyez-text";
    question.innerHTML = case_data.question;
    if (!case_data.question) h2.style.display = question.style.display = "none";
    caseInfo.appendChild(question);
    let ack = document.querySelector(".acknowledgement");
    ack.style.visibility = "visible";
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

function loadTranscript(section, transcriptDiv) {
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
            speakerImg.src = advocateImageBlobs[turn.speaker.identifier];
        }
        speakerImg.dataset.start = turn.start;
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
        speakerLabel.dataset.start = turn.start;
        textBlocks.appendChild(speakerLabel);
        textBlocks.className = "text-blocks";
        if (justices.includes(turn.speaker.identifier)) {
            textBlocks.classList.add("text-blocks-justice");
        } else {
            textBlocks.classList.add("text-blocks-advocate");
        }
        for (let block of turn.text_blocks) {
            let p = document.createElement('p');
            p.innerHTML = block.text;
            p.dataset.turn = turnNumber;
            p.dataset.textBlock = block.number;
            p.dataset.start = block.start;
            p.id = "text-block-" + block.number;
            textBlocks.appendChild(p);
        }
        turnDiv.appendChild(textBlocks);
        transcriptDiv.appendChild(turnDiv);
        turnNumber++;
    }
}

async function buildAdvocateProfile(sectionNumber, conversationDiv) {
    let advocateDiv = document.createElement('div');
    advocateDiv.className = "advocate";
    let img = document.createElement('img');
    img.className = "advocate-img";
    advocateDiv.appendChild(img);
    let advocateText = document.createElement('div');
    advocateText.className = "advocate-text";
    advocateDiv.appendChild(advocateText);
    let advocateName = document.createElement('p');
    advocateName.className = "advocate-name";
    advocateText.appendChild(advocateName);
    let advocateDescription = document.createElement('p');
    advocateDescription.className = "advocate-description";
    advocateText.appendChild(advocateDescription);
    conversationDiv.appendChild(advocateDiv);
    let justiceSpeakers = document.createElement('div');
    justiceSpeakers.className = "justice-speakers";
    conversationDiv.appendChild(justiceSpeakers);

    let sectionInfo = interactions_data.sections[sectionNumber];
    advocateName.innerHTML = "<span>" + sectionInfo.advocateName + "</span>";
    advocateDescription.innerHTML = sectionInfo.advocateDescription;

    const imgURL = "advocates/" + sectionInfo.advocateIdentifier + ".jpg";
    try {
        const response = await fetch(imgURL);
        if (!response.ok) throw new Error('Image not found');
        const blob = await response.blob();
        const objectURL = URL.createObjectURL(blob);
        advocateImageBlobs[sectionInfo.advocateIdentifier] = objectURL;
    } catch (error) {
        advocateImageBlobs[sectionInfo.advocateIdentifier] = placeholderAdvocateImage;
    }
    img.src = advocateImageBlobs[sectionInfo.advocateIdentifier];

    // show interactions
    let container = justiceSpeakers;
    container.innerHTML = "";
    for (let interaction of sectionInfo.interactions) {
        let img = document.createElement('img');
        img.src = document.getElementById('justice-' + interaction.justice).firstChild.src;
        img.id = "interaction-" + interaction.number;
        img.className = "interaction-img";
        img.dataset.startTurn = interaction.start;
        img.dataset.start = interaction.startTime;
        container.appendChild(img);
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
    setUpSection(0);
}

function loadNextOpinionAnnouncement() {
    currentOpinion++;
    loadOpinionAnnouncement(currentOpinion);
}

async function setUpSection(sectionNumber) {
    const main = document.querySelector("div.main");
    // make a new div for the section
    const sectionDiv = document.createElement('div');
    sectionDiv.id = "section-" + sectionNumber;
    sectionDiv.className = "section";
    main.appendChild(sectionDiv);
    const conversationDiv = document.createElement('div');
    conversationDiv.className = "conversation";
    sectionDiv.appendChild(conversationDiv);
    const transcriptDiv = document.createElement('div');
    transcriptDiv.className = "transcript";
    sectionDiv.appendChild(transcriptDiv);
    let section = sectionsObject[sectionNumber];

    await buildAdvocateProfile(sectionNumber, conversationDiv);
    loadTranscript(section, transcriptDiv);
}
