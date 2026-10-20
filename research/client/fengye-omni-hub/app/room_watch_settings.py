"""Machine-local alarm preferences; excluded from source publication."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'bridge'))
from room_list_model import validate_alert_settings

def read_file(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError,TypeError):
        return {}

def write_file(path, value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)
    return value

def load(path):
    value=read_file(path)
    try:
        return validate_alert_settings(value['threshold'],value['minutes'])
    except (OSError,ValueError,KeyError,TypeError):
        if 'threshold' not in value or 'minutes' not in value:
            stored=dict(value)
            stored.setdefault('threshold',4)
            stored.setdefault('minutes',1.0)
            try:
                write_file(Path(path),stored)
            except OSError:
                pass
        return 4,1.0

def save(path,threshold,minutes):
    x,y=validate_alert_settings(threshold,minutes)
    value=read_file(path)
    value['threshold']=x
    value['minutes']=y
    write_file(path,value)
    return x,y

def update(path,**fields):
    value=read_file(path)
    value.update(fields)
    return write_file(path,value)
