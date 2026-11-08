// Adapt the shared recording export to the existing player presentation.
export function selectRecording(index, term, docket, recordingId = '') {
    const matches = Object.values(index.recordings || {}).filter(r => String(r.term) === term && r.docket === docket);
    if (recordingId) return matches.find(r => r.recording_id === recordingId) || null;
    return matches.sort((a, b) => b.argument_date.localeCompare(a.argument_date) || a.recording_id.localeCompare(b.recording_id))[0] || null;
}

export function adaptRecording(recording, original, court) {
    if (recording.schema_version !== 1 || !recording.sections?.length) throw new Error('Unsupported recording');
    const people = new Map();
    const escape = text => String(text).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
    const members = original?.heard_by?.find(c => c?.members?.length)?.members || court;
    const metadata = {...(original || {}), ID: recording.recording_id, name: recording.case_name,
        term: recording.term, docket_number: recording.docket, heard_by: [{members}],
        timeline: [{event: 'Argued', dates: [Date.parse(recording.argument_date + 'T12:00:00Z') / 1000]},
            ...(original?.timeline || []).filter(e => e && e.event !== 'Argued')],
        href: original?.href || '', justia_url: original?.justia_url || '',
        first_party_label: original?.first_party_label || 'Petitioner', first_party: original?.first_party || recording.case_name.split(' v. ')[0],
        second_party_label: original?.second_party_label || 'Respondent', second_party: original?.second_party || '',
        question: original?.question || '', cloud_alignment: true, oyez_metadata: !!original};
    const sections = recording.sections.map(section => ({...section, turns: section.turns.map(turn => {
        const person = {...turn.speaker};
        person.identifier ||= person.name.toLowerCase().replace(/[^a-z0-9]+/g, '_');
        person.last_name ||= person.name.split(' ').at(-1);
        people.set(person.identifier, person);
        return {...turn, speaker: person, text_blocks: turn.text_blocks.map(block => ({...block, text: escape(block.text)}))};
    })}));
    metadata.advocates = [...people.values()].filter(p => p.kind === 'advocate').map(person => ({advocate: person, advocate_description: person.role || ''}));
    return {metadata, transcript: {media_file: [{href: recording.audio.url}], transcript: {sections}}};
}

export async function sharedRecording(term, docket, recordingId = '', fetcher = fetch) {
    const response = await fetcher('/podcast/alignment/index.json', {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('Transcript index unavailable');
    const entry = selectRecording(await response.json(), term, docket, recordingId);
    if (!entry) return null;
    const url = new URL(entry.url, 'https://scotusstats.com');
    if (url.origin !== 'https://scotusstats.com' || !url.pathname.startsWith('/podcast/alignment/')) throw new Error('Unexpected transcript URL');
    const result = await fetcher(url.pathname, {signal: AbortSignal.timeout(10000)});
    if (!result.ok) throw new Error('Transcript unavailable');
    const bytes = await result.arrayBuffer();
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('');
    if (digest !== entry.revision) throw new Error('Transcript revision differs');
    const recording = JSON.parse(new TextDecoder().decode(bytes));
    if (recording.recording_id !== entry.recording_id || String(recording.term) !== term || recording.docket !== docket || recording.argument_date !== entry.argument_date) throw new Error('Recording identity differs');
    return recording;
}

// Current-bench fallback when Oyez has no case metadata yet.
export const defaultCourt = [
  {
    "name": "John G. Roberts, Jr.",
    "identifier": "john_g_roberts_jr",
    "last_name": "Roberts",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/john_g_roberts_jr.thumb.png"
    },
    "roles": [
      {
        "role_title": "Chief Justice of the United States"
      }
    ]
  },
  {
    "name": "Clarence Thomas",
    "identifier": "clarence_thomas",
    "last_name": "Thomas",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/clarence_thomas.thumb.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Samuel A. Alito, Jr.",
    "identifier": "samuel_a_alito_jr",
    "last_name": "Alito",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/samuel_alito_jr.thumb.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Sonia Sotomayor",
    "identifier": "sonia_sotomayor",
    "last_name": "Sotomayor",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/sonia_sotomayor.thumb.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Elena Kagan",
    "identifier": "elena_kagan",
    "last_name": "Kagan",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/elena_kagan.thumb.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Neil Gorsuch",
    "identifier": "neil_gorsuch",
    "last_name": "Gorsuch",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/neil_gorsuch.thumb__0.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Brett M. Kavanaugh",
    "identifier": "brett_m_kavanaugh",
    "last_name": "Kavanaugh",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/Kavanaugh-thumb.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Amy Coney Barrett",
    "identifier": "amy_coney_barrett",
    "last_name": "Barrett",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/barret-thumb.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  },
  {
    "name": "Ketanji Brown Jackson",
    "identifier": "ketanji_brown_jackson",
    "last_name": "Jackson",
    "thumbnail": {
      "href": "https://raw.githubusercontent.com/DominikPeters/scotus-videos/f0733f21b55acb19a5b98fdd24f928435d2c1220/justices/thumbnail_ketanji_brown_jackson.png"
    },
    "roles": [
      {
        "role_title": "Associate Justice"
      }
    ]
  }
];
