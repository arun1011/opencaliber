"""Portable JSON policy profiles; no cloud IAM discovery or automatic application."""
import copy
import json
from pathlib import Path
from .agent_engine import validate_config
ROOT=Path(__file__).resolve().parents[1]

def validate_profile(value):
    if not isinstance(value,dict) or set(value)!={'schema_version','name','config'} or type(value['schema_version']) is not int or value['schema_version']!=1:raise ValueError('Profile requires schema_version 1, name and config')
    if not isinstance(value['name'],str) or not value['name'].strip() or len(value['name'])>120:raise ValueError('Profile name must be 1–120 characters')
    return {'schema_version':1,'name':value['name'],'config':validate_config(value['config'])}

def available_profiles():
    return {p.stem:validate_profile(json.loads(p.read_text(encoding='utf-8'))) for p in sorted((ROOT/'profiles').glob('*.json'))}

def load_profile(path):return validate_profile(json.loads(Path(path).read_text(encoding='utf-8')))

def export_profile(config,name='Custom policy'):return validate_profile({'schema_version':1,'name':name,'config':copy.deepcopy(config)})
