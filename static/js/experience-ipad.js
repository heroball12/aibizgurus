(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('ipadConfig').textContent);
  const handler=window.webkit?.messageHandlers?.guru;
  const post=state=>handler?.postMessage(state);
  window.addEventListener('guru:state',event=>post(event.detail));
  // Only an allowlisted command name crosses the native bridge, never JS from a URL.
  const allowed=new Set(['pause','resume','status','crm','inventory','reset','controls','signout']);
  window.guruAppCommand=command=>{
    if(!allowed.has(command))return;
    if(command==='signout'){
      window.dispatchEvent(new CustomEvent('guru:command',{detail:'pause'}));
      const token=document.querySelector('[name=csrfmiddlewaretoken]');
      if(!token)return;
      const form=document.createElement('form');form.method='POST';form.action=config.signout;
      form.append(token.cloneNode());document.body.append(form);form.submit();return;
    }
    window.dispatchEvent(new CustomEvent('guru:command',{detail:command}));
    if(!document.getElementById('experienceApp')&&command==='status'){
      post({screen:location.pathname.includes('/crm/')?'crm':'guide',ready:true,busy:false,state:'READY'});
    }
  };
  if(!document.getElementById('experienceApp'))window.guruAppCommand('status');
})();
