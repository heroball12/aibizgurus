export function validPage(directory, value) {
  return typeof value === 'string' && Object.hasOwn(directory, value) ? value : null;
}
export function followupDraft(args) {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return {};
  const limits = {name:150,email:254,phone:80,business_name:200,industry:150,message:4000};
  return Object.fromEntries(Object.entries(limits).filter(([key]) => typeof args[key] === 'string').map(([key,max]) => [key,args[key].slice(0,max)]));
}

export function isUserCaption(entry) {
  return Boolean(entry.local || /^runway-transcription-(user|human)-/.test(entry.id || '') || /^(user|human)(?:-|$)/.test(entry.participantIdentity || ''));
}
