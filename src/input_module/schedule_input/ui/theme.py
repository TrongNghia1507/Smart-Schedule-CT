import streamlit as st
from .i18n import tr

PALETTES={
 'light':dict(bg='#f3f6fb',surface='#ffffff',text='#263345',muted='#71829b',border='#dce5f0',soft='#eef4fa',blue='#2f78ba',header='#214f78',green='#3e8a42',stripe='#e4e9ef',event='#3989cc'),
 'dark':dict(bg='#111923',surface='#1b2634',text='#e4edf7',muted='#9cacc0',border='#334459',soft='#243449',blue='#75b7ef',header='#173d60',green='#398a4b',stripe='#2c3a4c',event='#337bb2')
}

def apply_theme(mode):
    p=PALETTES[mode]
    css=':root {'+''.join(f'--app-{k}:{v};' for k,v in p.items())+'}'
    alerts={'Warning':('#fff4d6','#704b00'),'Error':('#ffebeb','#9b2424'),'Info':('#eaf3ff','#20558c'),'Success':('#e6f4e8','#236333')} if mode=='light' else {'Warning':('#3b301c','#ffdb8a'),'Error':('#40242a','#ffb5ba'),'Info':('#20354d','#bbddff'),'Success':('#203b2c','#afe1bb')}
    for severity,(background,foreground) in alerts.items():
        selector=f'[data-testid="stAlertContainer"]:has([data-testid="stAlertContent{severity}"])'
        css+=f'{selector}{{background:{background}!important;color:{foreground}!important;border:1px solid {foreground}40;border-radius:10px}}{selector} p,{selector} div,{selector} span,{selector} a{{color:{foreground}!important}}'
    css+='''
    [data-testid="stExpander"] details,[data-testid="stExpander"] summary{background:var(--app-surface)!important;color:var(--app-text)!important}
    [data-testid="stExpander"] summary:hover{background:var(--app-soft)!important}
    [data-testid="stExpander"] summary p,[data-testid="stExpander"] summary span{color:var(--app-text)!important}
    [data-testid="stFileUploaderDropzone"]{background:var(--app-soft)!important;color:var(--app-text)!important;border:1px dashed var(--app-blue)!important;border-radius:10px}
    [data-testid="stFileUploader"] button{background:var(--app-surface)!important;color:var(--app-text)!important;border:1px solid var(--app-blue)!important}
    [data-testid="stFileUploader"] button:hover{background:var(--app-soft)!important}
    [data-testid="stFileUploader"] p,[data-testid="stFileUploader"] span,[data-testid="stFileUploader"] small{color:var(--app-text)!important}
    [data-testid="stFileUploader"] button:focus-visible,[data-testid="stExpander"] summary:focus-visible{outline:2px solid var(--app-blue);outline-offset:2px}
    .stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:var(--app-bg)!important;color:var(--app-text)!important}
    [data-testid="stHeader"]{background:transparent!important} [data-testid="stToolbar"]{display:none}
    [data-testid="stMainBlockContainer"]{max-width:1900px;padding:1rem 2rem 3rem}
    h1,h2,h3,h4,p,label,[data-testid="stWidgetLabel"],[data-testid="stMarkdownContainer"] {color:var(--app-text)}
    h3{font-size:1.1rem!important;color:var(--app-blue)!important}
    [data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:var(--app-muted)!important}
    [data-testid="stVerticalBlockBorderWrapper"]>div,[data-testid="stForm"], [data-testid="stExpander"] {background:var(--app-surface);border-color:var(--app-border)!important;border-radius:16px!important}
    [data-testid="stForm"]{border:0;padding:0}
    .st-key-settings_card,.st-key-table_card_True,.st-key-table_card_False,.st-key-calendar_card,.st-key-summary_card,.st-key-legend_card,.st-key-footer_card{background:var(--app-surface)!important;border:1px solid var(--app-border)!important;border-radius:16px!important;box-shadow:0 1px 3px #20305008}
    [data-testid="stDateInputField"],[data-testid="stDateInputFieldsScroller"],[data-testid="stTimeInput"]>div,[data-testid="stDateInputCalendarButton"],.react-aria-DateField,[data-type="literal"]{background:var(--app-surface)!important;color:var(--app-text)!important;border-color:var(--app-border)!important}
    [data-testid="stDateInputField"]{border:1px solid var(--app-border)!important;border-radius:8px}
    [data-testid="stButton"] button,[data-testid="stDownloadButton"] button,[data-testid="stFormSubmitButton"] button{background:var(--app-surface);color:var(--app-text);border:1px solid var(--app-border);border-radius:10px;min-height:42px}
    [data-testid="stButton"] button[kind="primary"],[data-testid="stFormSubmitButton"] button[kind="primary"]{background:var(--app-blue)!important;color:white!important;border-color:var(--app-blue)!important}
    button[kind="primary"] p{color:white!important}
    button[data-variant="segmented_control"]{background:var(--app-surface)!important;color:var(--app-text)!important;border-color:var(--app-border)!important;min-height:42px}
    button[data-variant="segmented_control"][aria-checked="true"]{background:var(--app-blue)!important;color:white!important;border-color:var(--app-blue)!important}
    button[data-variant="segmented_control"][aria-checked="true"] p{color:white!important}
    [data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="select"]>div,[data-baseweb="textarea"],input,textarea,[role="spinbutton"]{background:var(--app-surface)!important;color:var(--app-text)!important;border-color:var(--app-border)!important}
    [data-baseweb="popover"]>div,[role="listbox"],[role="option"],[data-baseweb="menu"]{background:var(--app-surface)!important;color:var(--app-text)!important}
    [role="dialog"]{background:var(--app-surface)!important;color:var(--app-text)!important;border:1px solid var(--app-border);border-radius:18px!important}
    [data-testid="stAlert"]{border-radius:10px}
    .app-banner{background:var(--app-header);color:white;border-radius:16px;padding:24px 28px;display:flex;align-items:center;justify-content:space-between;gap:24px;margin:0 0 12px}
    .app-banner strong{font-size:24px;letter-spacing:-.4px}.app-banner span{color:#c7dded;font-size:15px;margin-left:16px}
    .steps{display:flex;gap:10px;align-items:center;white-space:nowrap;font-size:13px}
    .step{border-radius:24px;padding:10px 16px;background:#ffffff20}.step.active{background:white;color:#214f78;font-weight:700}
    .status-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:8px 0}.badge{display:inline-block;border-radius:20px;padding:5px 12px;font-size:13px;font-weight:600}
    .badge.error{background:#fbe2e2;color:#b32929}.badge.warning{background:#fff0c8;color:#936500}.badge.info{background:#e0efff;color:#2367aa}.badge.ok{background:#def2df;color:#2d7332}
    .legend{display:flex;align-items:center;gap:12px;margin:16px 0;color:var(--app-text);font-size:14px}
    .swatch{height:20px;width:32px;border-radius:4px;background:var(--app-event);flex-shrink:0}.swatch.sleep{background:repeating-linear-gradient(135deg,var(--app-stripe) 0px,var(--app-stripe) 5px,var(--app-surface) 5px,var(--app-surface) 10px);border:1px solid var(--app-border)}.swatch.line{height:3px;background:#ea4335}
    .stApp .st-key-confirm_input button[kind="primary"],.stApp .st-key-confirm_snapshot button[kind="primary"]{background:var(--app-green)!important;color:white!important;border-color:var(--app-green)!important;width:100%}
    .st-key-confirm_input button p,.st-key-confirm_snapshot button p{color:white!important}
    @media(max-width:800px){[data-testid="stMainBlockContainer"]{padding:1rem}.app-banner{padding:18px;display:block}.app-banner strong{font-size:19px}.app-banner span{display:block;margin:8px 0}.steps{margin-top:15px;font-size:11px}.step{padding:8px}}
    '''
    st.html('<style>'+css+'</style>')
    return p

def banner(page):
    index=1 if page=='input' else 2
    subtitle=tr('Nhập dữ liệu' if index==1 else 'Xem trước lịch tuần')
    st.html(f'<div class="app-banner"><div><strong>Smart Weekly Scheduling</strong><span>{tr("Trang")} {index} · {subtitle}</span></div><div class="steps"><div class="step {"active" if index==1 else ""}">① {tr("Nhập dữ liệu")}</div><div>—</div><div class="step {"active" if index==2 else ""}">② {tr("Xem trước lịch")}</div></div></div>')


def status_badges(report):
    counts={s:sum(i.severity.value==s for i in report.issues) for s in ('Error','Warning','Info')}
    st.html(f'<div class="status-row"><span class="badge {"error" if counts["Error"] else "ok"}">● {counts["Error"]} {tr("lỗi")}</span><span class="badge warning">● {counts["Warning"]} {tr("cảnh báo")}</span><span class="badge info">● {counts["Info"]} {tr("ghi chú")}</span></div>')
