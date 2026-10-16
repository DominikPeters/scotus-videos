"""Evidence-preserving corrections to the first automated opinion-coding batch.

These are reviewed data corrections, not rules for interpreting future opinions.
Original model output and records stay in the private canonical migration audit.
"""
import copy
from stats_core import apply_coding, hierarchy, normalized_decision, validate_coding

REVISION='2026-10-15-reviewed-ot25'
OLD_FORMS={'majority','unanimous','unanimous judgment','unanimous judgment; opinion of the Court except Part IV-C',
           'unanimous judgment; majority opinion with partial concurrence',
           'Unanimous judgment with concurrence in the judgment','Unanimous judgment with separate concurrence in the judgment'}
NINE=['Roberts','Thomas','Alito','Sotomayor','Kagan','Gorsuch','Kavanaugh','Barrett','Jackson']

def coalition(label,majority,minority,evidence):
    return dict(label=label,majorityVoters=majority,minorityVoters=minority,abstainers=[],majoritySize=len(majority),minoritySize=len(minority),majorityJoiners=[],dissentingWriters=[],evidence=evidence)

def migrate(state,issues,provisions):
    if REVISION in state.get('migrations',{}):return []
    originals={};changes=[]
    for key,record in state['records'].items():
        decision=record.get('decision')
        if not (decision and decision.get('source')=='codex') and key not in ('2025/24-43','2025/24-856','2025/24-872'):continue
        originals[key]={'record':copy.deepcopy(record),'research':copy.deepcopy(state.get('research',{}).get(key))}
        if decision and 'opinionForm' not in decision:
            previous=decision['type']
            if previous in OLD_FORMS:form='majority'
            elif previous=='majority in part; plurality in part':form='plurality opinion'
            else:raise ValueError('Unreviewed old decision form: '+previous)
            decision.update(opinionForm=form,voteStatus='complete',judgmentParts=[])
            record['decision']=normalized_decision(decision)
        if key=='2025/24-872':
            record['decision']={'type':'dismissed as improvidently granted','opinionForm':'dismissed as improvidently granted','voteStatus':'unknown','majorityWriter':None,'judgmentParts':[],'source':'codex'}
        if key in ('2025/24-43','2025/24-856'):
            principal=['Roberts','Thomas','Alito','Gorsuch','Kavanaugh','Barrett'];others=['Sotomayor','Kagan','Jackson']
            details=record['opinionDetails'];evidence=' '.join(o['evidence'] for o in details)
            if key.endswith('24-856'):
                parts=[coalition('Alien Tort Statute',principal,others,evidence),coalition('Torture Victim Protection Act',principal+['Kagan','Jackson'],['Sotomayor'],evidence)];writer='Barrett'
            else:
                parts=[coalition('Equal Protection',principal,others,evidence),coalition('Title IX',NINE,[],evidence)];writer='Kavanaugh'
            record['decision']={'type':'mixed judgment','opinionForm':'majority','voteStatus':'mixed','majorityWriter':writer,'judgmentParts':parts,'source':'codex'}
        details=record.get('opinionDetails',[])
        for o in details:o.setdefault('partialJoiners',[])
        # Each correction is supported by the retained exact joining passage.
        edits={
          '2025/24-1046':[(1,['Thomas','Gorsuch'],'Part II-B')],
          '2025/24-856':[(2,['Kagan','Jackson'],'Parts I, II, III, V')],
          '2025/24-872':[(3,['Roberts','Gorsuch'],'Parts I, III, IV')],
          '2025/25-332':[(0,['Thomas'],'All except Part III-B')],
          '2025/25-95':[(0,['Thomas'],'All except Part II-B'),(2,['Gorsuch'],'All except footnote 1')],
        }
        for index,names,parts in edits.get(key,[]):
            opinion=details[index];opinion['joiners']=[n for n in opinion['joiners'] if n not in names]
            opinion['partialJoiners']=[{'justice':n,'parts':parts} for n in names]
        if key=='2025/25-1083':details[0]['partialJoiners']=[{'justice':n,'parts':'All except Part III-A'} for n in ['Gorsuch','Barrett']]
        if key=='2025/24-5774':
            full=['Roberts','Sotomayor','Kagan'];details[0]['joiners']=full
            details[0]['partialJoiners']=[{'justice':n,'parts':'All except Part IV-C'} for n in NINE if n not in full+['Jackson']]
            details[0]['parts']='Opinion of the Court except Part IV-C; Part IV-C is a four-Justice opinion.'
            del details[1]
        if key=='2025/24-482':
            record['issue']=hierarchy(issues['10390']);record['provenance']['issue'].update(code='10390',review='Federal retroactive punishment; SCDB Peugh v United States comparator (10390/122).')
        # Named statute without a dedicated entry uses SCDB's existing generic statute category.
        provisions_fixed={'2025/24-1021':('224','Interstate state sovereign immunity; SCDB Franchise Tax Board v Hyatt (2018), 80060/224.'),
          '2025/24-1063':('900','Holding rests on nonstatutory appeal-waiver principles and procedural common law, not the underlying medication claim.'),
          '2025/24-1238':('600','FAAAA 49 USC 14501(c), without a dedicated taxonomy entry.'),
          '2025/24-171':('600','Copyright Act contributory infringement; SCDB MGM v Grokster uses 600.'),
          '2025/24-889':('600','35 USC 271(b); SCDB Global-Tech v SEB uses 600.'),
          '2025/25-197':('600','Rooker-Feldman jurisdiction under 28 USC 1257/1331; statutory jurisdiction without a dedicated entry.')}
        if key in provisions_fixed:
            code,reason=provisions_fixed[key];record['legalProvision']=hierarchy(provisions[code])
            record['provenance']['legalProvision']={'source':'codex','source_uri':record['provenance']['decision']['source_uri'],'code':code,'review':reason}
        record.setdefault('provenance',{}).setdefault('decision',{'source':'codex','source_uri':state['research'][key].get('evidence',['Official docket'])[0]})
        value={'decision':record['decision'],'opinion_details':details,'evidence':state['research'][key].get('evidence') or ['Retained official joining passages in opinionDetails']}
        validate_coding(value,issues,provisions)
        record['decision']=normalized_decision(record['decision'])
        changes.append(key)
    state.setdefault('migrations',{})[REVISION]={'changes':changes,'originals':originals}
    return changes
