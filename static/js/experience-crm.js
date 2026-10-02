(() => {
  const app=document.getElementById('dealershipCRM');if(!app)return;
  let dirty=false,stopped=false;
  document.querySelectorAll('.ex-staff-form input,.ex-staff-form select,.ex-staff-form textarea').forEach(el=>el.addEventListener('input',()=>{dirty=true;}));
  document.getElementById('crmRefresh').onclick=()=>location.reload();
  const timer=setInterval(async()=>{
    if(document.hidden||stopped)return;
    try{const r=await fetch(app.dataset.stateUrl,{credentials:'same-origin',cache:'no-store'});if(r.status===404){stopped=true;document.getElementById('crmUpdate').hidden=false;document.getElementById('crmUpdate').firstChild.textContent='This prospect was reset or the session expired. Return to Axel to start again. ';return;}if(!r.ok)return;const state=await r.json();if(String(state.has_customer)!==app.dataset.hasCustomer||(state.updated&&Date.parse(state.updated)!==Date.parse(app.dataset.updated))){if(dirty)document.getElementById('crmUpdate').hidden=false;else location.reload();}}
    catch{document.getElementById('crmUpdate').hidden=false;document.getElementById('crmUpdate').firstChild.textContent='Connection interrupted. Your saved demo record is safe. ';}
  },8000);
  window.addEventListener('pagehide',()=>clearInterval(timer));
})();
