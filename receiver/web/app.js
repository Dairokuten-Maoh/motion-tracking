const conversationSession='web-'+crypto.randomUUID();
let token = '';
let audioUrls = [];
let loadVersion = 0;
let askVersion = 0, askController = null, spokenAnswer = '';
const $ = id => document.getElementById(id);
const timeLabel = seconds => new Date(seconds * 1000).toLocaleTimeString('en-GB', {timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',second:'2-digit'});
$('day').value = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
function node(tag, text, className) { const el = document.createElement(tag); if(text !== undefined) el.textContent = text; if(className) el.className = className; return el; }
async function api(path) {
  const response = await fetch(path, {headers:{Authorization:'Bearer '+token},cache:'no-store'});
  if (!response.ok) throw new Error(response.status === 401 ? 'Pairing token not accepted.' : 'Request failed ('+response.status+').');
  return response;
}
function resetAudio() { for(const url of audioUrls) URL.revokeObjectURL(url); audioUrls = []; }
function section(parent, title, items, emptyText) {
  parent.append(node('h3',title));
  if(!items.length) {parent.append(node('p',emptyText,'subtle'));return;}
  for(const item of items) {
    const box=node('div',undefined,'summary-item'); box.append(node('p',item.text));
    const evidence=node('div',undefined,'evidence'), link=node('a','Transcript evidence'); link.href='#clip-'+item.source_id;
    link.onclick=()=>{const clip=$('clip-'+item.source_id);if(clip)clip.open=true;};
    evidence.append(link,node('div',item.quote));box.append(evidence);parent.append(box);
  }
}
function render(groups) {
  resetAudio(); $('timeline').replaceChildren();
  const clips=groups.flatMap(g=>g.clips);
  $('clips-count').textContent=clips.length;
  $('entries-count').textContent=groups.filter(g=>g.entry).length;
  $('pending-count').textContent=clips.filter(c=>c.state==='pending').length;
  if(!groups.length) {$('timeline').append(node('div','No recordings match this date and search.','empty'));return;}
  for(const group of groups) {
    const card=node('article',undefined,'entry'), head=node('div',undefined,'entry-head');
    head.append(node('span',timeLabel(group.window).slice(0,5)+' — '+timeLabel(group.window+1800).slice(0,5),'time'));
    head.append(node('span',group.open?'Current period':group.refreshing?'Summary updating':'Period complete','badge'));card.append(head);
    if(group.entry) {
      section(card,'Recorded interactions',group.entry.summary,'No supported interaction details.');
      const columns=node('div',undefined,'columns'),tasks=node('div'),notable=node('div');
      section(tasks,'Possible tasks · ownership unverified',group.entry.possible_tasks,'No explicit task candidates found.');
      section(notable,'Notable moments',group.entry.notable_moments,'No additional notable moments found.');
      columns.append(tasks,notable);card.append(columns);
      card.append(node('p','AI-generated from available transcripts · check evidence before relying on it.','subtle'));
    } else card.append(node('p',group.open?'A silent summary will be generated after this half-hour ends.':'Summary queued. Transcripts are available below.','subtle'));
    if(group.error)card.append(node('p',group.error,'error'));
    card.append(node('h3','Source recordings · '+group.clips.length));
    for(const clip of group.clips) {
      const details=node('details',undefined,'clip');details.id='clip-'+clip.id;
      details.append(node('summary',timeLabel(clip.started)+' · '+(clip.state==='done'?'Transcript ready':clip.state)));
      details.append(node('p',clip.transcript || clip.error || (clip.state==='done'?'No speech detected.':'Awaiting transcription.')));
      details.append(node('p','Recording archive: '+(clip.cloud_state || 'local only'),'subtle'));
      if(clip.audio_available) {
        const play=node('button','Load recording','secondary');play.type='button';details.append(play);
        play.onclick=async()=>{play.disabled=true;try{const response=await api('/audio/'+clip.id);const url=URL.createObjectURL(await response.blob());audioUrls.push(url);const player=node('audio');player.controls=true;player.src=url;details.append(player);play.remove();}catch(e){play.textContent=e.message;play.disabled=false;}};
      }else details.append(node('p','Original recording is no longer available.','subtle'));
      card.append(details);
    }
    $('timeline').append(card);
  }
}
async function load() {
  const version = ++loadVersion, requestedToken = token;
  $('message').textContent='Loading history…';
  try { const response=await api('/timeline?'+new URLSearchParams({day:$('day').value,q:$('query').value}));const groups=await response.json();if(version!==loadVersion || requestedToken!==token)return;render(groups);$('workspace').hidden=false;$('pair').hidden=true;$('lock').hidden=false;$('message').textContent='';}
  catch(e){if(version===loadVersion)$('message').textContent=e.message;}
}
$('login').onsubmit=e=>{e.preventDefault();token=$('token').value.trim();$('token').value='';load();};
$('filters').onsubmit=e=>{e.preventDefault();load();};
$('refresh').onclick=load;
$('day').onchange=()=>{if(token)load();};
$('lock').onclick=()=>{token='';loadVersion++;resetConversation();resetAudio();$('timeline').replaceChildren();$('workspace').hidden=true;$('pair').hidden=false;$('lock').hidden=true;$('message').textContent='';};

function stopSpeaking(){if('speechSynthesis' in window)window.speechSynthesis.cancel();}
function resetConversation(){askVersion++;if(askController)askController.abort();stopSpeaking();spokenAnswer='';$('answer').hidden=true;$('answer-text').textContent='';$('answer-sources').replaceChildren();$('question').value='';$('ask-status').textContent='';$('ask-button').disabled=false;}
$('ask-form').onsubmit=async event=>{
  event.preventDefault();
  const question=$('question').value.trim(),day=$('day').value,requestedToken=token,version=++askVersion;
  if(!question || !day)return;
  if(askController)askController.abort();askController=new AbortController();
  stopSpeaking();spokenAnswer='';$('answer').hidden=true;$('ask-button').disabled=true;
  $('ask-status').textContent='Jarvis is processing your request. Archive answers may take a minute while the local model loads…';
  try{
    const response=await fetch('/ask',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({question,day,session:conversationSession}),signal:askController.signal,cache:'no-store'});
    const result=await response.json();
    if(version!==askVersion || token!==requestedToken)return;
    if(!response.ok)throw new Error(result.error || 'Unable to answer right now.');
    spokenAnswer=result.answer;$('answer-text').textContent=result.answer;
    $('answer-scope').textContent=result.source==='conversation'?'Conversation':result.source==='web'?'Web search snippets - retrieved '+new Date(result.retrieved_at).toLocaleString():result.source==='google_calendar'?'Primary Google Calendar ? Taipei time':day+' · '+result.coverage.selected_clips+' of '+result.coverage.total_clips+' transcribed recordings considered'+(result.coverage.partial?' · Partial coverage':'');
    $('answer-sources').replaceChildren();
    for(const source of result.web_sources || []){
      const url=new URL(source.url);
      if(!['https:','http:'].includes(url.protocol))continue;
      const link=node('a',source.title);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';
      const evidence=node('div',undefined,'evidence');evidence.append(link);$('answer-sources').append(evidence);
    }
    for(const source of result.citations){
      const evidence=node('div',undefined,'evidence'),link=node('a','Source recording · '+timeLabel(source.started));link.href='#clip-'+source.source_id;
      link.onclick=async event=>{event.preventDefault();$('day').value=day;$('query').value='';await load();const clip=$('clip-'+source.source_id);if(clip){clip.open=true;clip.scrollIntoView({behavior:'smooth',block:'center'});}};
      evidence.append(link,node('div',source.quote));$('answer-sources').append(evidence);
    }
    $('answer').hidden=false;
    $('ask-status').textContent=result.source==='conversation'?'Conversation reply':result.source==='web'?(result.insufficient_evidence?'Search evidence is limited; inspect the sources.':'Summary of search snippets; full pages were not read.'):result.source==='google_calendar'?'Calendar command result':result.insufficient_evidence?'The available evidence is limited.':'Answer linked to transcript evidence. Interpretations may still be imperfect.';
  }catch(error){if(version===askVersion && error.name!=='AbortError')$('ask-status').textContent=error.message;}
  finally{if(version===askVersion)$('ask-button').disabled=false;}
};
$('speak-answer').onclick=()=>{
  if(!spokenAnswer)return;
  if(!('speechSynthesis' in window)){$('ask-status').textContent='Spoken playback is not supported by this browser.';return;}
  const voice=window.speechSynthesis.getVoices().find(v=>v.localService && /^en([-_]|$)/i.test(v.lang));
  if(!voice){$('ask-status').textContent='No local English voice is available yet. Try again shortly or enable an English voice in your system settings.';return;}
  stopSpeaking();const utterance=new SpeechSynthesisUtterance(spokenAnswer);utterance.voice=voice;utterance.lang=voice.lang;
  utterance.onerror=()=>{$('ask-status').textContent='Spoken playback failed. The text answer is still available.';};
  window.speechSynthesis.speak(utterance);
};
$('stop-speaking').onclick=stopSpeaking;
if('speechSynthesis' in window)window.speechSynthesis.getVoices();
window.addEventListener('pagehide',stopSpeaking);
