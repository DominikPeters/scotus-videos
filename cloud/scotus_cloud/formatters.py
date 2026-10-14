"""Preserve established video descriptions, chapters and timestamp comments."""
import ast,re
from types import SimpleNamespace
from .presentation_sources import verified_source


def format_interactions(metadata,audio,duration,*,wikipedia_url=None,oyez_content_used=False):
    """Execute the original formatting block, excluding I/O and interactive work."""
    source=verified_source('formatters/argument.py')
    # A one-section recording has no earlier chapter when testing for rebuttal.
    source=source.replace('if section_counter == len(sections) - 1 and speaker_name == chapters[0]["title"]:', 'if chapters and section_counter == len(sections) - 1 and speaker_name == chapters[0]["title"]:')
    tree=ast.parse(source)
    begin=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='chapters' for t in n.targets))
    end=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='json_object' and isinstance(t.slice,ast.Constant) and t.slice.value=='term' for t in n.targets))+1
    justices={m['name']:m for m in metadata['heard_by'][0]['members']}
    advocates={a['advocate']['name']:(a['advocate']['name'],a['advocate']['identifier'],a['advocate'].get('description',''),a['advocate']['last_name']) for a in metadata['advocates']}
    namespace={'case_metadata':metadata,'oral_argument_transcript':audio,'sections':audio['transcript']['sections'],
        'json_object':{'sections':{},'mp3_length':duration},'docket_number':metadata['docket_number'],
        'justices':justices,'advocates':advocates,'all_advocates':set(advocates),
        'datetime':__import__('datetime'),'re':re,
        'requests':SimpleNamespace(get=lambda url:SimpleNamespace(status_code=200 if url==wikipedia_url else 404))}
    exec(compile(ast.Module(body=tree.body[begin:end],type_ignores=[]),'original-self-aligned-format','exec'),namespace)
    result=namespace['json_object']
    description=result['youtube_description']
    old='Video produced based on information and transcripts on oyez.org, licensed under a CC-BY-NC License (https://creativecommons.org/licenses/by-nc/4.0/).'
    if oyez_content_used:
        description=description.replace(old,'Case information based on oyez.org, licensed under a CC-BY-NC License (https://creativecommons.org/licenses/by-nc/4.0/).')
    else:
        description=description.replace(old+'\n','').replace('*Facts of the case (from oyez.org)*','*Facts of the case*')
        description=re.sub(r'^Oyez\.org:.*\n','',description,flags=re.M)
    if not metadata.get('justia_url'): description=description.replace('Justia: \n','')
    result['youtube_description']=description
    return result


def timestamp_comment(interactions):
    tree=ast.parse(verified_source('formatters/chapters_comment.py'))
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef)]
    captured={}
    class API:
        def commentThreads(self): return self
        def insert(self,**args): captured.update(args['body']);return self
        def execute(self): return {}
    ns={};exec(compile(ast.Module(body=functions,type_ignores=[]),'original-timestamps','exec'),ns)
    import contextlib,io
    with contextlib.redirect_stdout(io.StringIO()):ns['add_timestamp_comment'](API(),'private-format-only',interactions)
    return captured['snippet']['topLevelComment']['snippet']['textOriginal']
