"""Fetch a U.S. Reports syllabus (head matter) from the Caselaw Access Project static site."""
import json,sys,subprocess,re,html,os
v,p=sys.argv[1],sys.argv[2]
os.makedirs('cap',exist_ok=True)
m=f'cap/meta-{v}.json'
if not os.path.exists(m): subprocess.run(['curl','-s',f'https://static.case.law/us/{v}/CasesMetadata.json','-o',m])
meta=json.load(open(m))
e=next((e for e in meta if any(c.get('cite')==f'{v} U.S. {p}' for c in e.get('citations',[]))),None)
if not e: print(v,p,'not found');sys.exit()
url=f"https://static.case.law/us/{v}/cases/{e['file_name']}.json"
d=json.loads(subprocess.run(['curl','-s',url],capture_output=True,text=True).stdout)
head=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',d['casebody'].get('head_matter',''))))
ops='\n\n'.join(o.get('type','')+' '+str(o.get('author'))+': '+re.sub(r'\s+',' ',o.get('text','')) for o in d['casebody'].get('opinions',[]))
open(f'cap-{v}-{p}.txt','w').write(url+'\n'+d['name_abbreviation']+' ('+d['decision_date']+')\n'+head+'\n\n'+ops)
print(v,p,d['name_abbreviation'],d['decision_date'],len(head))
