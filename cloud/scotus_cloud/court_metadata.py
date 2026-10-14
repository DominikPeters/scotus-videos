"""Normalize incomplete Oyez inputs without changing public formatters."""

def normalized_case_source(original):
    # Null placeholders mean unavailable fields, so existing defaults can run.
    data={key:value for key,value in (original or {}).items() if value is not None}
    courts=data.get('heard_by')
    if isinstance(courts,list):
        valid=[]
        for court in courts:
            members=court.get('members') if isinstance(court,dict) else None
            if isinstance(members,list) and members and all(
                isinstance(m,dict) and m.get('identifier') and m.get('name') and m.get('last_name') and
                isinstance(m.get('thumbnail'),dict) and m['thumbnail'].get('href') for m in members):
                valid.append(court)
        data['heard_by']=valid
    else:data.pop('heard_by',None)
    return data
