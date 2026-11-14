"""Presentation preferences never enter the task/snapshot schema."""
import json
from pathlib import Path
import streamlit as st

COLORS = ['#b95175','#d95177','#d78078','#dc4f30','#e56536','#df762f',
          '#e39733','#ebbd49','#d9c25c','#bcc44c','#81aa58','#439363','#50ad80',
          '#409c92','#499ed0','#6389df','#858ac2','#726dc0','#b09bcb',
          '#a379af','#a756b8','#917166','#808080','#a59889']

def load_colors(path):
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        return {k:v for k,v in data.items() if v in COLORS}
    except (OSError,ValueError,AttributeError):
        return {}

def save_colors(path, colors):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(colors),encoding='utf-8'); tmp.replace(path)

def color_picker(key, current, lang='vi'):
    st.caption('Màu hiển thị' if lang=='vi' else 'Display color')
    st.session_state.setdefault(key,current)
    def choose(value):
        st.session_state[key]=value
    st.html(f'<style>.st-key-{key}_grid [data-testid="stHorizontalBlock"]{{flex-direction:row!important;flex-wrap:nowrap!important;gap:8px!important}}.st-key-{key}_grid [data-testid="stColumn"]{{min-width:0!important;width:auto!important;flex:1 1 0!important}}.st-key-{key}_grid{{max-width:620px}}</style>')
    with st.container(key=key+'_grid'):
        for row in (COLORS[:13],COLORS[13:]):
            cols=st.columns(13)
            for col,color in zip(cols,row):
                name=f'{key}_{color[1:]}'
                selected=st.session_state[key]==color
                st.html(f'<style>.st-key-{name} button{{background:{color}!important;border-radius:50%!important;min-height:26px!important;height:26px!important;width:26px!important;padding:0!important;border:2px solid {"var(--app-text)" if selected else "transparent"}!important}}.st-key-{name} button p{{color:#101820!important}}</style>')
                col.button('✓' if selected else '\u200b',key=name,help=color,on_click=choose,args=(color,))
    st.button('Mặc định' if lang=='vi' else 'Default',key=key+'_default',on_click=choose,args=(None,))
    return st.session_state[key]
