/* Native grid: source values remain in the CRM; drafts live only in this tab. */
function parseSheetPaste(text) {
  const rows = [[]]; let value = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') { if (quoted && text[i+1] === '"') {value += '"'; i++;} else if (quoted || value === '') quoted = !quoted; else value += c; }
    else if (!quoted && (c === '\t' || c === '\n' || c === '\r')) {
      rows[rows.length-1].push(value); value = '';
      if (c !== '\t') { if (c === '\r' && text[i+1] === '\n') i++; rows.push([]); }
    } else value += c;
  }
  rows[rows.length-1].push(value);
  if (rows.length > 1 && rows.at(-1).length === 1 && rows.at(-1)[0] === '') rows.pop();
  return rows;
}
if (typeof module !== 'undefined') module.exports = {parseSheetPaste};
if (typeof document !== 'undefined') (() => {
  const app = document.getElementById('leadSheetApp'); if (!app) return;
  const el = id => document.getElementById(id), title = el('sheetTitle'), status = el('sheetStatus');
  let data, rows, group = 'Contact', page = 0, dirty = false, busy = false, retryPayload = null;
  let selected = new Set(), errors = [], search = '', savedTitle = '';
  const size = 40;
  const makeRow = () => ({key:crypto.randomUUID(),values:{status:'new',lead_temperature:'cold'},original:null});
  const notice = text => {el('sheetNotice').hidden = !text; el('sheetNotice').textContent = text;};
  function load(packet) {
    data = packet; savedTitle = packet.title; title.value = packet.title;
    rows = packet.rows.map(r => ({...r, original:{...r.values}, values:{...r.values,...r.changes}}));
    if (!rows.length && data.kind === 'leads') rows = Array.from({length:15},makeRow);
    dirty = packet.rows.some(r => r.changes); group = 'Contact'; page = 0; selected.clear(); errors = []; retryPayload = null;
    el('sheetErrors').hidden = true;
    el('sheetSubtitle').textContent = data.kind === 'prospects' ? 'Edit Finder results here. Save businesses to the pipeline from Lead Finder.' : 'Save once. Your pipeline and assessment notes stay in sync.';
    el('addRows').hidden = data.kind === 'prospects';
    notice([data.total > data.maxRows ? `Showing the first ${data.maxRows} of ${data.total} records. Narrow the original view to work on the remaining records.` : '',data.missing ? `${data.missing} unavailable records were left out because they were removed or reassigned.` : '',...(data.warnings||[])].filter(Boolean).join(' '));
    render(); updateStatus();
  }
  function changes(row) {
    return Object.fromEntries(data.columns.filter(c => row.values[c.key] !== undefined && (!row.original || String(row.values[c.key]??'') !== String(row.original[c.key]??''))).map(c => [c.key,String(row.values[c.key]??'')]));
  }
  function markDirty() { dirty = true; updateStatus(); }
  function updateStatus(message) {
    status.textContent = message || (dirty ? 'Unsaved changes' : data.saved ? 'Saved to CRM' : 'Ready to edit');
    el('saveSheet').disabled = busy;
    app.querySelectorAll('#sheetGrid input,#sheetGrid select,#sheetGrid textarea,#sheetTitle,#addRows,#openSheetFile,#removeRows').forEach(control => control.disabled = busy || !!retryPayload);
    el('removeRows').disabled = busy || !!retryPayload || !selected.size;
  }
  const visibleCols = () => data.columns.filter(c => c.key === 'business_name' || c.group === group);
  const visibleRows = () => rows.filter(r => !search || Object.values(r.values).some(v => String(v).toLowerCase().includes(search)));
  function render() {
    const tabs = el('sheetGroups'); tabs.replaceChildren();
    [...new Set(data.columns.map(c=>c.group))].forEach(name => {
      const b = document.createElement('button'); b.type='button'; b.role='tab'; b.textContent=name; b.setAttribute('aria-selected',String(group===name));
      b.onclick=()=>{group=name;render();}; tabs.append(b);
    });
    const cols = visibleCols(), filtered = visibleRows();
    page = Math.max(0,Math.min(page,Math.ceil(filtered.length/size)-1));
    const head = el('sheetGrid').tHead, body = el('sheetGrid').tBodies[0]; head.replaceChildren(); body.replaceChildren();
    const hr = document.createElement('tr'), first = document.createElement('th'); first.scope='col'; first.textContent='#'; hr.append(first);
    cols.forEach(c=>{const th=document.createElement('th');th.scope='col';th.textContent=c.label;hr.append(th);});head.append(hr);
    filtered.slice(page*size,(page+1)*size).forEach(row => {
      const tr=document.createElement('tr'), td=document.createElement('td'), label=document.createElement('label'), check=document.createElement('input');
      check.type='checkbox';check.checked=selected.has(row.key);check.setAttribute('aria-label',`Select row ${rows.indexOf(row)+1}`);
      check.onchange=()=>{check.checked?selected.add(row.key):selected.delete(row.key);updateStatus();};
      label.append(check,document.createTextNode(String(rows.indexOf(row)+1)));td.append(label);tr.append(td);
      cols.forEach(col=>{
        const cell=document.createElement('td'), input=document.createElement(col.type==='select'?'select':col.type==='textarea'?'textarea':'input');
        if(input.tagName==='INPUT') {input.type=col.type==='number'?'text':col.type; if(col.type==='number')input.inputMode='decimal';}
        input.maxLength=col.maxLength;input.dataset.row=row.key;input.dataset.field=col.key;input.setAttribute('aria-label',`${col.label}, row ${rows.indexOf(row)+1}`);
        const value=String(row.values[col.key]??'');
        if(col.type==='select'){
          const choices=col.choices.map(([v,l])=>[String(v),l]);
          const labelMatch=choices.find(([,l])=>l.toLowerCase()===value.toLowerCase());
          if(labelMatch) row.values[col.key]=labelMatch[0];
          if(!choices.some(([v])=>v===String(row.values[col.key]??''))) choices.unshift([value,value||'Choose…']);
          choices.forEach(([v,l])=>{const o=document.createElement('option');o.value=v;o.textContent=l;input.append(o);});
        }
        input.value=String(row.values[col.key]??'');
        const error=errors.find(e=>e.key===row.key&&e.field===col.key);
        if(error){input.setAttribute('aria-invalid','true');input.title=error.message;}
        if(Object.hasOwn(changes(row),col.key))cell.classList.add('is-dirty');
        input.oninput=()=>{row.values[col.key]=input.value;cell.classList.add('is-dirty');input.removeAttribute('aria-invalid');markDirty();};
        input.onpaste=event=>{
          const text=event.clipboardData.getData('text/plain');
          if(!text.includes('\t') && (!/[\r\n]/.test(text)||col.type==='textarea'))return;
          event.preventDefault();const pasted=parseSheetPaste(text), start=filtered.indexOf(row), field=cols.indexOf(col);
          if(pasted.some(r=>r.length>cols.length-field)){notice('The pasted selection has more columns than this group. Paste the matching columns into each group, or use Open file to map a complete sheet.');return;}
          const extra=Math.max(0,start+pasted.length-filtered.length);
          if(rows.length+extra>data.maxRows || (extra&&data.kind==='prospects')){notice('The pasted rows do not fit. Lead sheets support 500 rows; Finder sheets only edit existing results.');return;}
          for(let i=0;i<extra;i++){const r=makeRow();rows.push(r);filtered.push(r);}
          pasted.forEach((values,i)=>values.forEach((v,j)=>{filtered[start+i].values[cols[field+j].key]=v;}));markDirty();render();
        };
        input.onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();const next=filtered[filtered.indexOf(row)+1];if(next){page=Math.floor((filtered.indexOf(row)+1)/size);render();focusCell(next.key,col.key);}}};
        cell.append(input);
        if(col.key==='business_name'&&row.url){const a=document.createElement('a');a.href=row.url;a.textContent='↗';a.className='record-link';a.title='Open CRM record';cell.append(a);}
        tr.append(cell);
      });body.append(tr);
    });
    el('sheetRowCount').textContent=`${rows.length} rows${search?` · ${filtered.length} matching`:''} · ${selected.size} selected`;
    el('sheetPage').textContent=`${filtered.length?page*size+1:0}–${Math.min((page+1)*size,filtered.length)} of ${filtered.length}`;
    el('sheetPrev').disabled=page===0;el('sheetNext').disabled=(page+1)*size>=filtered.length;
    updateStatus();
  }
  function focusCell(key,field){app.querySelector(`[data-row="${CSS.escape(key)}"][data-field="${CSS.escape(field)}"]`)?.focus();}
  function showErrors(result) {
    errors=result.errors||[];const box=el('sheetErrors');box.replaceChildren();box.hidden=false;
    const p=document.createElement('p');p.textContent=result.error||'Unable to save. Your edits are still here.';box.append(p);
    errors.forEach(error=>{const b=document.createElement('button');b.type='button';b.textContent=`Row ${error.row}: ${error.message}`;b.onclick=()=>{search='';el('sheetSearch').value='';group=data.columns.find(c=>c.key===error.field)?.group||'Contact';page=Math.floor(rows.findIndex(r=>r.key===error.key)/size);render();focusCell(error.key,error.field);};box.append(b);});
    render();box.scrollIntoView({block:'nearest',behavior:'smooth'});
  }
  async function save() {
    if(busy)return false;
    const payload=retryPayload||{snapshot:data.snapshot,mutation_id:crypto.randomUUID(),title:title.value,rows:rows.map(r=>({key:r.key,changes:changes(r)}))};
    busy=true;updateStatus('Saving…');
    try{
      const response=await fetch(app.dataset.saveUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':app.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify(payload),signal:AbortSignal.timeout(30000)});
      if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('session');
      const result=await response.json();retryPayload=null;
      if(!response.ok){showErrors(result);return false;}
      load(result);history.replaceState(null,'',result.url);updateStatus('Saved just now');return true;
    }catch(error){retryPayload=payload;notice('The save could not be confirmed. Your edits are still here. Press Save to CRM again to safely check or retry the same save. If your session expired, sign in in another tab first.');return false;}
    finally{busy=false;updateStatus();}
  }
  el('saveSheet').onclick=save;
  title.oninput=markDirty;
  el('addRows').onclick=()=>{const count=Math.min(10,data.maxRows-rows.length);for(let i=0;i<count;i++)rows.push(makeRow());page=Math.floor((rows.length-1)/size);search='';el('sheetSearch').value='';markDirty();render();};
  el('removeRows').onclick=()=>{rows=rows.filter(r=>!selected.has(r.key));selected.clear();markDirty();render();notice('Removed from this sheet. Existing CRM records will be kept. Save to keep the sheet layout.');};
  el('sheetPrev').onclick=()=>{page--;render();};el('sheetNext').onclick=()=>{page++;render();};
  el('sheetSearch').oninput=event=>{search=event.target.value.trim().toLowerCase();page=0;render();};
  el('openSheetFile').onclick=()=>{if(!dirty||confirm('Open another file? Unsaved changes in this sheet will be discarded after the file opens successfully.'))el('sheetFile').click();};
  el('sheetFile').onchange=async event=>{
    const file=event.target.files[0];if(!file)return;
    if(file.size>5*1024*1024){notice('Choose a file up to 5 MB.');return;}
    const form=new FormData();form.append('file',file);busy=true;updateStatus('Opening file…');
    try{
      const response=await fetch(app.dataset.importUrl,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':app.querySelector('[name=csrfmiddlewaretoken]').value},body:form});
      const result=await response.json();if(!response.ok){showErrors(result);return;}load(result);dirty=true;history.replaceState(null,'',app.dataset.exportBase.replace('export/','new/'));notice(['File opened for review. Save to CRM applies the rows.',...(result.warnings||[])].join(' '));
    }catch(error){notice('Could not open this file. Check your connection and session, then try again.');}
    finally{busy=false;event.target.value='';updateStatus();}
  };
  async function download(format){if(busy)return;if((dirty||!data.saved)&&!await save())return;window.location.assign(`${data.url}export/?format=${format}`);}
  el('exportSheet').onclick=()=>download('xlsx');el('exportCSV').onclick=()=>download('csv');
  window.addEventListener('beforeunload',event=>{if(dirty||retryPayload){event.preventDefault();event.returnValue='';}});
  document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save();}});
  load(JSON.parse(el('leadSheetData').textContent));
  if(new URLSearchParams(location.search).has('open'))notice('Choose Open file to review an Excel or CSV file here before saving.');
})();
