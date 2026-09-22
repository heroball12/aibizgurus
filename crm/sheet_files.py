"""Small, dependency-free Excel/CSV adapter for deployable CRM file exchange."""
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from .importers import CSV_ALIASES, csv_key, _read_shared_strings, _read_workbook_sheets, _read_xlsx_sheet
from .intelligence import csv_safe
from .sheet_schema import MAX_ROWS

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
ET.register_namespace('', NS)
ET.register_namespace('r', REL)


def letter(n):
    result = ''
    while n:
        n, rem = divmod(n-1, 26)
        result = chr(65+rem)+result
    return result


def child(parent, name, attrs=None, text=None):
    element = ET.SubElement(parent, '{'+NS+'}'+name, attrs or {})
    if text is not None: element.text = str(text)
    return element


def xml(element):
    return ET.tostring(element, encoding='utf-8', xml_declaration=True)


def cell(row, col, number, value, style='0'):
    node = child(row, 'c', {'r':f'{letter(col)}{number}','t':'inlineStr','s':style})
    # XML 1.0 control characters cannot be serialized as valid workbook text.
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
    child(child(node,'is'),'t',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'},value)


def make_xlsx(schema, rows, kind='leads'):
    root = ET.Element('{'+NS+'}worksheet')
    views = child(root,'sheetViews')
    child(child(views,'sheetView',{'workbookViewId':'0'}),'pane',{'xSplit':'1','ySplit':'1','topLeftCell':'B2','activePane':'bottomRight','state':'frozen'})
    cols = child(root,'cols')
    for i,col in enumerate(schema,1):
        child(cols,'col',{'min':str(i),'max':str(i),'width':'42' if col['type']=='textarea' else '26','customWidth':'1'})
    child(cols,'col',{'min':str(len(schema)+1),'max':str(len(schema)+1),'width':'12','hidden':'1','customWidth':'1'})
    data = child(root,'sheetData')
    header = child(data,'row',{'r':'1','ht':'32','customHeight':'1'})
    for i,label in enumerate([c['label'] for c in schema]+['_crm_record'],1):cell(header,i,1,label,'1')
    for n,values in enumerate(rows,2):
        row = child(data,'row',{'r':str(n),'ht':'30','customHeight':'1'})
        for i,value in enumerate(values,1):cell(row,i,n,value,'2')
    child(root,'autoFilter',{'ref':f'A1:{letter(len(schema))}{max(2,len(rows)+1)}'})
    choices = [(i,c) for i,c in enumerate(schema,1) if c['choices']]
    validations = child(root,'dataValidations',{'count':str(len(choices))})
    lists = ET.Element('{'+NS+'}worksheet')
    list_data = child(lists,'sheetData')
    for index in range(max((len(c['choices']) for _,c in choices), default=0)):
        row = child(list_data,'row',{'r':str(index+1)})
        for i,(_,col) in enumerate(choices,1):
            if index < len(col['choices']):cell(row,i,index+1,col['choices'][index][1])
    workbook = ET.Element('{'+NS+'}workbook')
    sheets = child(workbook,'sheets')
    child(sheets,'sheet',{'name':'Prospects' if kind=='prospects' else 'Leads','sheetId':'1','{'+REL+'}id':'rId1'})
    child(sheets,'sheet',{'name':'_Lists','sheetId':'2','state':'hidden','{'+REL+'}id':'rId2'})
    names = child(workbook,'definedNames')
    for n,(colnum,col) in enumerate(choices,1):
        name = 'Options_'+str(n)
        child(names,'definedName',{'name':name},f"'_Lists'!${letter(n)}$1:${letter(n)}${len(col['choices'])}")
        val = child(validations,'dataValidation',{'type':'list','allowBlank':'1','showErrorMessage':'1','errorTitle':'Choose a listed value','error':'Select a value from the dropdown.','sqref':f'{letter(colnum)}2:{letter(colnum)}{max(MAX_ROWS+1,len(rows)+1)}'})
        child(val,'formula1',text=name)
    styles = f'''<styleSheet xmlns="{NS}"><fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFF2CF7A"/><sz val="11"/><name val="Calibri"/></font><font><color rgb="FF3344AA"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF2D1C40"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf><xf numFmtId="49" fontId="2" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    types = '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'''
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml',types)
        zf.writestr('_rels/.rels',f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="{REL}/styles" Target="styles.xml"/></Relationships>')
        zf.writestr('xl/workbook.xml',xml(workbook))
        zf.writestr('xl/worksheets/sheet1.xml',xml(root))
        zf.writestr('xl/worksheets/sheet2.xml',xml(lists))
        zf.writestr('xl/styles.xml',styles)
    return buf.getvalue()


def make_csv(schema, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c['label'] for c in schema]+['_crm_record'])
    writer.writerows([[csv_safe(str(v)) for v in row] for row in rows])
    return ('\ufeff'+buf.getvalue()).encode('utf-8')


def read_file(uploaded, schema):
    if not uploaded or uploaded.size > 5*1024*1024:
        raise ValueError('Choose an Excel (.xlsx) or CSV file up to 5 MB.')
    name = uploaded.name.lower()
    date1904 = False
    warnings = []
    try:
        if name.endswith('.csv'):
            table = []
            for row in csv.reader(io.StringIO(uploaded.read().decode('utf-8-sig'))):
                table.append(row)
                if len(table)>MAX_ROWS+16: raise ValueError(f'Open up to {MAX_ROWS} populated rows at a time.')
        elif name.endswith('.xlsx'):
            with zipfile.ZipFile(uploaded) as zf:
                if len(zf.infolist())>2000 or sum(i.file_size for i in zf.infolist())>50*1024*1024:
                    raise ValueError('This workbook is too large to open. Export a smaller sheet.')
                sheets = _read_workbook_sheets(zf)
                if not sheets: raise ValueError('The workbook has no visible sheets.')
                table = _read_xlsx_sheet(zf,sheets[0][1],_read_shared_strings(zf))
                if len(sheets)>1: warnings.append(f'Opened the first visible tab: {sheets[0][0]}. Use the existing tracker importer to process all tabs.')
                props = ET.fromstring(zf.read('xl/workbook.xml')).find('{'+NS+'}workbookPr')
                date1904 = props is not None and props.get('date1904') in ('1','true')
        else: raise ValueError('Use .xlsx or .csv. Save older .xls workbooks as .xlsx first.')
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError, RuntimeError, csv.Error):
        raise ValueError('This file could not be read. Save an unencrypted .xlsx or UTF-8 CSV and try again.')
    aliases = {csv_key(c['key']):c['key'] for c in schema}
    aliases.update({csv_key(c['label']):c['key'] for c in schema})
    aliases.update({'_crm_record':'_crm_record','source_url':'source_url','source_url_':'source_url'})
    for key, names in CSV_ALIASES.items():
        if key in aliases:
            aliases.update({csv_key(n):key for n in names})
    aliases.update({'temperature':'lead_temperature','original_notes':'notes','summary_notes':'cleaned_notes','phone_number':'phone','current_workflow':'workflow','current_tools':'tools','main_bottleneck':'bottleneck','business_goal':'goal','ai_strategy':'strategy','pricing_notes':'pricing'})
    start = next((i for i,row in enumerate(table[:15]) if any(aliases.get(csv_key(v)) in ('business_name','name','phone','email') for v in row)),None)
    if start is None: raise ValueError('No lead column headers found. Download the blank template to see the supported columns.')
    headers = [aliases.get(csv_key(v)) for v in table[start]]
    used = [v for v in headers if v]
    if len(used)!=len(set(used)): raise ValueError('Two columns map to the same lead field. Keep one column per field.')
    unknown = [v for v,k in zip(table[start],headers) if v and not k]
    if unknown: warnings.append('Ignored unrecognized columns: '+', '.join(unknown)[:400])
    rows = []
    for raw in table[start+1:]:
        values = {key:raw[i] for i,key in enumerate(headers) if key and i<len(raw)}
        if not any(v.strip() for v in values.values()): continue
        date = values.get('follow_up_date','').strip()
        if re.fullmatch(r'\d{1,5}(\.0+)?',date):
            values['follow_up_date'] = ((datetime(1904,1,1) if date1904 else datetime(1899,12,30))+timedelta(days=float(date))).date().isoformat()
        # Defaults for blank template cells; existing rows keep intentional clears.
        if not values.get('_crm_record'):
            for key in ('status','lead_temperature'):
                if not values.get(key): values.pop(key,None)
        rows.append(values)
        if len(rows)>MAX_ROWS: raise ValueError(f'Open up to {MAX_ROWS} populated rows at a time.')
    return rows,warnings
