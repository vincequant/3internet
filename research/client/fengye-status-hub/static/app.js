'use strict';
const $ = id => document.getElementById(id);
let data = null;
let busy = false;
let searching = false;
let browserError = false;
const states = {unknown:'目前未知',seated:'目前在座',reconnecting:'正在重連',failed:'連接失敗',absent:'目前不在座'};
const sourceReasons = {
  collector_stopped:['主機成員採集已停止 · 保留最後觀測','vkquant Mac 可以連接，但主機成員採集器目前未運行；最後在座記錄不能代表現在。'],
  watch_unavailable:['等待房間觀測','採集器已啟動，尚未取得本輪主機成員表；保留先前記錄。'],
  expired:['房間觀測已過期','Mac 已連接，但主機成員表超過 20 秒未更新；不能判定現在是否仍在座。'],
  remote_offline:['遠端連接不可用 · 保留最後觀測','未能連接或讀取 vkquant Mac，不能核對當前狀態。'],
  file_replay:['檔案回放 · 非即時狀態','目前讀取保存的觀測，不能判定現在是否仍在座。'],
  historical_observation:['歷史觀測 · 現況未知','目前只有歷史記錄，等待本輪主機觀測。'],
  invalid_timestamp:['觀測時間異常','觀測時間與本機不一致，暫不判定即時狀態。'],
  not_checked:['尚未連接觀測來源','等待首次讀取 vkquant Mac。'],
  no_session:['尚未加入本局會話','由風夜 Hub 進入房間後，這裡只顯示該局會話自己看到的資料。'],
  session_stopped:['本局會話已停止','保留該局最後資料與原時間；不會顯示其他局或歷史 run。'],
  session_expired:['本局會話停止回應','會話紀錄超過 20 秒未更新；可能已斷線或被停止。'],
  session_unknown:['本局會話狀態未知','尚未取得有效的會話時間戳。']
};
const fmt = ts => typeof ts === 'number' ? new Date(ts*1000).toLocaleString('zh-TW',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}) : '—';
const ago = ts => {if(typeof ts !== 'number')return '—';const s=Math.max(0,Math.floor(Date.now()/1000-ts));return s<60?s+' 秒前':s<3600?Math.floor(s/60)+' 分前':s<86400?Math.floor(s/3600)+' 小時前':Math.floor(s/86400)+' 天前';};
const text = (id,value) => {$(id).textContent=value??'—';};
function cell(row,value,cls=''){const td=document.createElement('td');td.textContent=value??'—';td.className=cls;row.appendChild(td);return td;}
function isStale(){return !data||browserError||data.source.stale||typeof data.source.observed_at!=='number'||Date.now()/1000-data.source.observed_at>20;}
function updateAges(){
  if(!data)return;
  const stale=isStale(), g=data.ghost, connected=data.transport.status==='online'&&!browserError;
  document.body.dataset.stale=String(stale);
  text('observed-time',fmt(data.source.observed_at));
  text('source-tag',stale?'最後已知':'即時觀測');
  const state=stale?'unknown':g.state;
  text('ghost-state',states[state]||states.unknown);
  $('ghost-state').className='state '+(state==='seated'?'good':state==='reconnecting'?'warn':state==='failed'?'bad':'');
  text('ghost-note',stale?(data.source.observed_at?`最後記錄：${states[g.last_known_state]||'未知'} · ${ago(data.source.observed_at)}`:'尚無可靠的會話觀測。'):(data.session?'本局會話無主機成員表；狀態以會話自身資料為準。':'依主機 DLL 成員表核對。'));
  const faction=g.start_snapshot||{}, factionKnown=faction.status!=='unknown'&&typeof faction.observed_at==='number';
  const factionHistoric=factionKnown&&(stale||faction.status==='historical'||Date.now()/1000-faction.observed_at>20);
  text('faction-label',factionHistoric?'歷史開局快照中的勢力':'開局快照中的勢力');
  text('faction-name',!factionKnown?'未知':faction.assignment==='unbound'?'未綁定':faction.faction_name||'已綁定（名稱未知）');
  text('faction-time',factionKnown?'cmd7 · '+fmt(faction.observed_at)+' · '+(faction.identity_match?'快照與成員 ID 相符':'目前成員 ID 未核實')+'；僅為當時快照。':'尚無可核對的完整 cmd7 快照；不能判定為無勢力。');
  const statusEl=$('connection');statusEl.className='source-pill'+(connected?' online':'');statusEl.lastElementChild.textContent='vkquant Mac · '+(connected?'已連接':data.transport.status==='file'?'檔案回放':data.transport.status==='not_checked'?'未連接':'離線');
  $('notice').className='notice'+(!stale?' live':'');
  const reason = data.source.status==='live'&&stale?'expired':data.source.status;
  const notice = sourceReasons[reason]||['即時狀態未知 · 保留最後觀測','資料不足，暫不能判定現在是否仍在座。'];
  text('notice-title',browserError?'本機 Hub 連接中斷':stale?notice[0]:(data.session?'本局會話資料已更新':'主機成員觀測已更新'));
  text('notice-description',browserError?'頁面保留先前記錄；請確認本機 Hub 仍在運行。':stale?notice[1]:(data.session?'僅顯示當前加入這局的會話資料，每 5 秒同步。':'依主機 DLL 表核對風夜是否在座，每 5 秒同步。'));
  text('checked-at','連接檢查 '+fmt(data.transport.checked_at));
  text('activity-age',g.activity_at?ago(g.activity_at):'未核實');const small=document.createElement('small');small.textContent=stale?'最後已知活動':'最近成員活動';$('activity-age').appendChild(small);
  const collector=data.collector||{}, capture=['capture_only','ready_on_valid_cmd7','p34_spectator','p42_spectator','hub_room_session'].includes(collector.mode);
  const captureFresh=collector.fresh&&!browserError&&typeof collector.observed_at==='number'&&Date.now()/1000-collector.observed_at<=20;
  text('watchdog',capture?(captureFresh?'接收中':collector.process_present?'記錄已過期':'已停止'):g.watchdog_started_at?(!stale&&g.watchdog_process_present?'已武裝':'曾武裝 · 現況未知'):'尚未確認');
  if(capture)text('response-note',(captureFresh?'本輪接收記錄。':'最後已知接收記錄。')+(collector.mode==='hub_room_session'?'本局會話探針；只記錄本局自己收到的封包與控制回執。':collector.mode==='ready_on_valid_cmd7'?'準備回覆待驗；收到 cmd10 仍需核對遊戲畫面。':collector.mode==='p34_spectator'?'P34 旁聽鏈；D8 判決見情報卡，收到資料不等於行已消隱。':collector.mode==='p42_spectator'?'P42/P43 開局前摘席鏈；指令流見下方解碼區；收到資料不等於棋盤可見。':'本模式不發 cmd23，不自動宣告準備完成；收到資料不等於開局成功。'));
  const hostStale=browserError||data.host.stale||typeof data.host.observed_at!=='number'||Date.now()/1000-data.host.observed_at>20;
  text('host-tag',hostStale?'最後目標':'連接目標');
  text('host-note',data.host.session||data.host.virtual_ip?(hostStale?'保留本輪最後連接目標；是否仍在房內以成員觀測為準。':'現有鏈的連接目標；開局結果需另行核實。'):'本輪尚未取得房間目標資料。');
  const q=data.room_query;const roomFresh=q.fresh&&!browserError&&typeof q.observed_at==='number'&&Date.now()/1000-q.observed_at<=60;
  text('room-time','觀測 '+fmt(q.observed_at)+' · '+ago(q.observed_at));
  text('room-count',q.status==='replies_received'&&roomFresh?q.rooms.length:'—');
  text('room-status',q.error|| (q.status==='replies_received'?(roomFresh?'已收到房間回覆。':'以下為歷史房間回覆，等待重新查詢。'):q.status==='unconfirmed_empty'?'上次查詢未收到房間回覆，線路狀態未知。':'尚未讀取房間列表。'));
  $('search-rooms').disabled=!connected||searching;
  $('search-rooms').title=connected?'透過現有認證中繼做一次房間搜尋':'目前無法連接觀測來源';
  text('members-source',stale?'歷史 DLL 記錄':'主機 DLL 表');
  text('footer-clock',new Date().toLocaleTimeString('zh-TW',{hour12:false})+' · READ ONLY');
  intelWindowTick();
}
function renderRooms(){
  if(!data)return;
  const query=$('room-filter').value.trim().toLowerCase();const q=data.room_query;
  const rooms=q.rooms.filter(r=>[r.name,r.host,r.virtual_ip].some(v=>String(v??'').toLowerCase().includes(query)));
  const body=$('rooms');body.replaceChildren();
  if(!rooms.length){
    const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.className='empty';
    const icon=document.createElement('span');icon.className='empty-icon';icon.textContent='⌁';
    const title=document.createElement('strong');title.textContent=query?'沒有符合搜尋的房間':'目前沒有可判定的房間資料';
    const note=document.createElement('p');note.textContent=query?'請更換房名、房主或 IP 關鍵字。':'未收到搜尋回覆，不作「零房間」判斷。';
    td.append(icon,title,note);tr.appendChild(td);body.appendChild(tr);
  }
  for(const r of rooms){const tr=document.createElement('tr');cell(tr,r.name);cell(tr,r.host);cell(tr,r.virtual_ip,'mono');cell(tr,Number.isInteger(r.current)&&Number.isInteger(r.maximum)?`${r.current} / ${r.maximum}`:'—');cell(tr,q.fresh?'搜尋回覆':'歷史回覆','dim');body.appendChild(tr);}
  text('room-help','搜尋不加入房間 · 對局是否已開始尚未核實');
}
const eventNames={joined:'幽靈會話已加入',registered:'應用行註冊已驗證',register_unverified:'註冊未取得主機讀取驗證',watchdog_started:'看門狗已武裝',wd_trigger_seen:'已看到觸發文件',wd_fired:'cmd23 看門狗呼叫完成',wd_complete:'三次觸發已完成',send_enter:'開始呼叫發送',send_return:'發送呼叫返回',wd_err:'看門狗回報錯誤',wd_session_dead:'幽靈會話已失效',received_packet:'收到完整資料包',packet_release:'資料包釋放呼叫返回',receiver_error:'接收處理錯誤',window_bindings:'接收窗口已綁定',host_gate_receipt:'主機接收序號已核對',open_return:'加入會話呼叫返回',abort:'接收探針中止',closed:'接收探針已關閉',snapshot_stored:'已保存房間快照',ready_once:'按已核對資料準備回覆',scenario_checked:'劇本校驗已檢查',prep_blocked:'準備回覆暫停',start_command_received:'收到開局指令（畫面待驗）'};
function render(reply){
  data=reply;browserError=false;
  const g=data.ghost;
  text('member-id','會話 ID '+(g.member?.id??'—'));
  text('reconnect',g.member?.reconnecting==null?'—':String(g.member.reconnecting)+(data.source.stale?' · 歷史':''));
  text('cmd23',g.cmd23_attempts==null?'—':`${g.cmd23_attempts} / ${g.cmd23_returns??'—'}`);
  const collector=data.collector||{}, capture=['capture_only','ready_on_valid_cmd7','p34_spectator','p42_spectator','hub_room_session'].includes(collector.mode);
  text('response-title',capture?(collector.mode==='ready_on_valid_cmd7'?'接收與準備回覆':collector.mode==='p34_spectator'?'接收與同步（P34）':collector.mode==='p42_spectator'?'接收與摘席（P42）':'回應與接收'):'回應與觸發');text('probe-label',collector.mode==='p42_spectator'?'接收探針（P42）':collector.mode==='p34_spectator'?'接收探針（P34）':capture?'接收探針':'看門狗');
  $('ready-row').hidden=!['ready_on_valid_cmd7','p34_spectator'].includes(collector.mode);text('cmd9',collector.cmd9_attempts==null?'—':`${collector.cmd9_attempts} / ${collector.cmd9_returns??'—'}`);
  $('cmd23-row').hidden=capture;$('capture-row').hidden=!capture;$('capture-cmd-row').hidden=!capture;
  text('capture-counts',collector.packet_count==null?'—':`${collector.packet_count} / ${collector.release_calls??'—'}`);
  text('capture-cmd',Number.isInteger(collector.last_cmd)?'cmd'+collector.last_cmd:'尚無可辨識命令');
  if(!capture)text('response-note','呼叫返回與開局成功分別核對。');
  text('session-name',data.host.session);text('host-ip',data.host.virtual_ip);text('current-line',data.line);
  const members=$('members');members.replaceChildren();
  for(const m of data.members){const tr=document.createElement('tr');cell(tr,m.name,'member-name'+(m.name==='风夜'?' watched':''));cell(tr,m.id,'mono');cell(tr,m.failed?'失敗標誌 '+m.failed:m.reconnecting?'重連標誌 '+m.reconnecting:'重連 0','dim');members.appendChild(tr);}
  if(!data.members.length){const tr=document.createElement('tr');const td=cell(tr,'沒有可用成員觀測','dim');td.colSpan=3;members.appendChild(tr);}
  const events=$('events');events.replaceChildren();
  for(const e of data.events.slice(-10).reverse()){const li=document.createElement('li');const t=document.createElement('time');t.textContent=typeof e.wall==='number'?new Date(e.wall*1000).toLocaleTimeString('zh-TW',{hour12:false}):'—';const dot=document.createElement('span');dot.className='event-dot';const label=document.createElement('span');label.textContent=(eventNames[e.ev]||e.ev)+(Number.isInteger(e.cmd)?' · cmd'+e.cmd:'')+(e.label?' · '+e.label:'')+(e.rc!=null?' · rc='+e.rc:'');li.append(t,dot,label);events.appendChild(li);}
  if(!data.events.length){const li=document.createElement('li');li.textContent='尚無可用事件。';li.className='dim';events.appendChild(li);}
  const directory=data.directory||{}, lines=directory.lines||[];text('directory-time','歷史目錄 · '+fmt(directory.observed_at));$('directory').replaceChildren();
  for(const line of lines){const card=document.createElement('div');card.className='line-card'+(line.name?.includes('多线3')?' selected':'');const name=document.createElement('h3');name.textContent=line.name;const endpoint=document.createElement('p');endpoint.className='mono';endpoint.textContent=(line.server||'目錄未提供地址')+(line.port?':'+line.port:'');card.append(name,endpoint);$('directory').appendChild(card);}
  if(!lines.length)text('directory','尚無線路目錄。');
  text('run-name',(data.session?'本局會話：':'來源運行：')+(data.source.run_name||'未取得')+(data.session?' · 僅當前加入這局的資料':' · '+(data.source.kind==='handoff_observation'?'接手時觀測記錄':'現有採集器資料')));
  text('chain',data.chain.length?data.chain.map(p=>`${p.role} · PID ${p.pid??'—'}`+(p.line?' · '+p.line:'')).join('\n'):'未取得現有進程狀態。');
  renderIntel();updateAges();renderRooms();
}
const intelCmdNames={0:'玩家通知',3:'初始快照',6:'劇本請求',7:'開局快照',10:'開局指令',11:'取消',18:'遊戲數據',26:'逐輪通知'};
const intelStates={running_not_yet_registered:'運行中 · 未註冊',ended_historical_pointer:'已收窗 · 歷史指針'};
let feedFilter='all';
const clsFromHex=hex=>{const i=String(hex||'').toLowerCase().indexOf('4353616e496e6574');if(i<0)return null;let out='';for(let p=i;p<hex.length-1;p+=2){const b=parseInt(hex.substr(p,2),16);if(b<0x20||b>0x7e)break;out+=String.fromCharCode(b);}return out||null;};
function intelWindowTick(){
  const p=data&&data.p34;if(!p){text('intel-window','—');return;}
  const w=p.window||{};
  if(typeof w.end_wall!=='number'){text('intel-window','—');return;}
  const rem=Math.floor(w.end_wall-Date.now()/1000);
  text('intel-window',(w.anchored_by==='d8'?'被動窗':'觀察窗')+(rem>0?` · 剩餘 ${Math.floor(rem/60)} 分`:' · 已結束'));
}
function feedItems(p){
  const items=[];
  for(const f of (p.frames||[])){const cmdName=Number.isInteger(f.cmd)?(intelCmdNames[f.cmd]||('cmd'+f.cmd)):(f.cls||'未知');items.push({wall:f.wall,kind:'frame',label:`${cmdName} · type ${f.type??'—'} · ${f.len??'—'}B · ${f.sha8||''}`});}
  const sy=p.sync||{};
  for(const b of (sy.nonempty||[])){for(const r of (b.records||[])){const what=r.action?`指令 · ${r.action}${r.detail?(' · '+r.detail):''}`:(clsFromHex(r.raw)||'遊戲數據');items.push({wall:b.wall,kind:'data',label:`${what} · 第 ${b.round??'—'} 輪 · ${r.len??'—'}B · ${r.sha8||''}`});}}
  for(const e of ((p.control||{}).events||[])){items.push({wall:e.wall,kind:'control',label:`${e.ev}${e.text?(' · '+e.text):''}${e.rc!=null?(' · rc='+e.rc):''}${e.reason?(' · '+e.reason):''}`});}
  for(const m of ((p.chat||{}).messages||[])){items.push({wall:m.wall,kind:'chat',label:`聊天 · ${m.sender_name?(m.sender_name+'：'):''}${m.text||'—'}`});}
  items.sort((a,b)=>(b.wall||0)-(a.wall||0));
  return items;
}
function renderFeed(p){
  const el=$('intel-feed');el.replaceChildren();
  const items=feedItems(p);
  const shown=items.filter(i=>feedFilter==='all'||i.kind===feedFilter).slice(0,80);
  text('feed-count',String(shown.length));
  if(!shown.length){const li=document.createElement('li');li.className='dim';li.textContent=items.length?'（此篩選無項目）':'尚無情報。';el.appendChild(li);return;}
  for(const it of shown){const li=document.createElement('li');li.className='feed-'+it.kind;const t=document.createElement('time');t.textContent=typeof it.wall==='number'?new Date(it.wall*1000).toLocaleTimeString('zh-TW',{hour12:false}):'—';const dot=document.createElement('span');dot.className='event-dot';const kind=document.createElement('span');kind.className='feed-kind';kind.textContent={frame:'幀',data:'數據',chat:'聊天',control:'控制'}[it.kind]||it.kind;const label=document.createElement('span');label.textContent=it.label;li.append(t,dot,kind,label);el.appendChild(li);}
}
function renderIntel(){
  const p=data&&data.p34;
  const feed=$('intel-feed'),chatEl=$('intel-chat'),body=$('intel-snapshot'),se=$('intel-sync');
  if(!p){
    text('intel-run','未取得');text('hero-state','尚未加入本局會話');text('hero-counters','—');text('intel-window','—');
    text('feed-count','0');text('cmd-count','0');text('intel-commands-note','尚無情報。');feed.replaceChildren();
    const li=document.createElement('li');li.className='dim';li.textContent='尚無情報。';feed.appendChild(li);
    chatEl.replaceChildren();const ch=document.createElement('li');ch.className='dim';ch.textContent='尚無聊天。';chatEl.appendChild(ch);
    text('chat-count','0');
    body.replaceChildren();const tr=document.createElement('tr'),td=cell(tr,'尚無快照。','dim');td.colSpan=6;body.appendChild(tr);
    se.replaceChildren();const pe=document.createElement('p');pe.className='dim small';pe.textContent='尚無。';se.appendChild(pe);
    text('control-state','未就緒 · 無在線 probe');$('control-chat').disabled=true;$('control-stop').disabled=true;
    return;
  }
  text('intel-run',p.run_name||'—');
  const sessionPhases={lobby:'大廳中',joining:'進房中',room:'已在房間',starting:'啟動中',disconnected:'連線斷開',stopped:'已停止',stale:'停止回應'};
  text('hero-state',(data.session?('本局會話 · '+(sessionPhases[data.session.phase]||data.session.phase||'—')):(intelStates[p.pointer_state]||p.pointer_state||'—'))+(p.registration_verified?' · 註冊已驗證':' · 註冊未證')+(data.session?(data.session.fresh?' · 即時':' · 非即時'):(p.live_probe?' · 在線':' · 離線')));
  const c=p.counters||{},d8=p.d8||{};
  text('hero-counters',`收幀 ${c.received??'—'} · 釋放 ${c.released??'—'} · 錯誤 ${c.errors??'—'} · 輪數 ${c.rounds??'—'} · D8後 ${c.received_after_d8??'—'} · D8 ${d8.sent_once?'已發':'未發'}`);
  renderFeed(p);
  chatEl.replaceChildren();
  const msgs=((p.chat||{}).messages)||[];
  text('chat-count',String(msgs.length));
  if(!msgs.length){const li=document.createElement('li');li.className='dim';li.textContent='尚無聊天（WM_CHAT '+((p.chat||{}).wm_chat_count??0)+' · type3 '+((p.chat||{}).type3_frames??0)+'）。';chatEl.appendChild(li);}
  for(const m of msgs){const li=document.createElement('li'),t=document.createElement('time'),dot=document.createElement('span'),label=document.createElement('span');t.textContent=typeof m.wall==='number'?new Date(m.wall*1000).toLocaleTimeString('zh-TW',{hour12:false}):'—';dot.className='event-dot';label.textContent=(m.sender_name?(m.sender_name+'：'):'')+(m.text||'—');li.append(t,dot,label);chatEl.appendChild(li);}
  const live=!!p.live_probe&&data.transport&&data.transport.status==='online';
  text('control-state',live?'就緒 · probe 在線':'未就緒 · 無在線 probe');
  $('control-chat').disabled=!live;$('control-stop').disabled=!live;
  const ctrl=p.control||{};
  if(ctrl.pending&&ctrl.pending.id)text('control-status','待執行：'+(ctrl.pending.op==='chat'?'發言':'收窗')+' · '+String(ctrl.pending.id).slice(0,10)+'…（探針每秒輪詢）');
  else if(ctrl.last_result&&ctrl.last_result.id)text('control-status','最近：'+(ctrl.last_result.op==='chat'?'發言':'收窗')+' · rc='+ctrl.last_result.rc+' · '+fmt(ctrl.last_result.wall));
  else text('control-status','僅在風夜在線（run 運行中）時可用；每條請求一次性、失敗不重試。');
  const ce=$('control-events');ce.replaceChildren();
  const evs=ctrl.events||[];
  if(!evs.length){const li=document.createElement('li');li.className='dim';li.textContent='尚無控制事件。';ce.appendChild(li);}
  for(const e of evs.slice(-6).reverse()){const li=document.createElement('li'),t=document.createElement('time'),dot=document.createElement('span'),label=document.createElement('span');t.textContent=typeof e.wall==='number'?new Date(e.wall*1000).toLocaleTimeString('zh-TW',{hour12:false}):'—';dot.className='event-dot';label.textContent=e.ev+(e.text?(' · '+e.text):'')+(e.rc!=null?(' · rc='+e.rc):'')+(e.reason?(' · '+e.reason):'');li.append(t,dot,label);ce.appendChild(li);}
  body.replaceChildren();
  const block=(p.snapshots||{}).start||(p.snapshots||{}).initial;
  if(block&&Array.isArray(block.rows)&&block.rows.length){
    for(const r of block.rows){const tr=document.createElement('tr');
      const name=r.name==null||r.name===''?(r.id?'（空白）':'（空位）'):r.name;
      cell(tr,r.i);cell(tr,name,'member-name'+(typeof r.name==='string'&&r.name.includes('风夜')?' watched':''));cell(tr,r.id,'mono');cell(tr,r.w4);cell(tr,r.state42);cell(tr,r.faction==null||r.faction===''?'—':r.faction);body.appendChild(tr);}
    text('intel-snapshot-note',(block.cmd===7?'cmd7 開局快照':'cmd3 初始快照')+' · '+fmt(block.observed_at)+(data.session?' · 本局會話快照。':' · 快照時點資料，非即時。'));
  }else{const tr=document.createElement('tr'),td=cell(tr,'尚無完整八行快照。','dim');td.colSpan=6;body.appendChild(tr);text('intel-snapshot-note',data.session?'本局尚未收到開局快照（cmd3／cmd7）。':'cmd7 快照時點的資料；不是即時勢力。');}
  se.replaceChildren();
  const sy=p.sync||{};
  const ne=sy.nonempty||[];
  const cmds=p.commands||{};
  text('cmd-count',String((cmds.rows||[]).length));
  const totals=Object.entries(cmds.totals||{}).map(([k,v])=>`${k}×${v}`).join(' · ');
  text('intel-commands-note',(cmds.available?'解碼器就緒':'解碼器不可用（僅顯示原文）')+(cmds.decoder?(' · '+cmds.decoder):'')+(totals?(' · '+totals):'')+(cmds.note?(' · '+cmds.note):''));
  if(!ne.length){const pe=document.createElement('p');pe.className='dim small';pe.textContent=`${sy.rounds??0} 輪同步中未見非空記錄（指令記錄）。`;se.appendChild(pe);}
  for(const b of ne){const box=document.createElement('div');box.className='intel-batch';
    const h=document.createElement('p');h.className='small';h.textContent=`第 ${b.round??'—'} 輪 · ${fmt(b.wall)} · ${(b.records||[]).length} 條記錄`;box.appendChild(h);
    for(const r of (b.records||[])){
      const line=document.createElement('p');line.className='small';
      line.textContent=r.action?`指令 · ${r.action}${r.detail?(' · '+r.detail):''} · sender=${r.sender??'—'}`:`未解碼${r.kind!=null?`（kind ${r.kind}）`:''} · sender=${r.sender??'—'} len=${r.len??'—'}`;
      box.appendChild(line);
      if(r.raw){const det=document.createElement('details'),sum=document.createElement('summary'),pre=document.createElement('pre');sum.textContent='原文'+(r.sha8?(' '+r.sha8):'');pre.textContent=r.raw;det.append(sum,pre);box.appendChild(det);}}
    se.appendChild(box);}
  intelWindowTick();
}
async function refresh(search=false){
  if(busy)return;busy=true;searching=search;$('refresh').disabled=true;
  if(search){$('search-rooms').disabled=true;$('search-rooms').textContent='正在讀取…';}
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),search?29000:13000);
  try{const response=await fetch(search?'/api/rooms/refresh':'/api/status',{method:search?'POST':'GET',cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error('HTTP '+response.status);render(await response.json());}
  catch{browserError=true;if(data)updateAges();else{text('notice-title','本機 Hub 尚未返回狀態');text('notice-description','請確認 Hub 仍在運行。');}}
  finally{clearTimeout(timer);busy=false;searching=false;$('refresh').disabled=false;$('search-rooms').textContent='讀取房間列表 ↗';if(data)updateAges();}
}
$('refresh').addEventListener('click',()=>refresh());$('search-rooms').addEventListener('click',()=>refresh(true));$('room-filter').addEventListener('input',renderRooms);
async function controlSend(payload){
  try{const response=await fetch('/api/control',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});return await response.json();}
  catch{return {status:'error',error:'本機 Hub 連接中斷'};}
}
$('control-chat').addEventListener('click',async()=>{
  const input=$('control-text'),msg=input.value.trim();
  if(!msg)return;
  $('control-chat').disabled=true;
  const result=await controlSend({op:'chat',text:msg});
  text('control-status',result.status==='sent'?('已送出 '+String(result.id).slice(0,10)+'…，待風夜執行（rc 見事件列）'):('發言失敗：'+(result.error||result.status)));
  if(result.status==='sent')input.value='';
  $('control-chat').disabled=false;
  refresh();
});
$('feed-filters').addEventListener('click',ev=>{
  const btn=ev.target.closest('button');
  if(!btn||!btn.dataset.kind)return;
  feedFilter=btn.dataset.kind;
  for(const b of $('feed-filters').querySelectorAll('button'))b.classList.toggle('active',b===btn);
  if(data&&data.p34)renderFeed(data.p34);
});
$('control-stop').addEventListener('click',async()=>{
  if(!confirm('確定要讓風夜收窗退出？（正常退出會話，之後需重新點火）'))return;
  const result=await controlSend({op:'stop'});
  text('control-status',result.status==='sent'?('收窗已送出 '+String(result.id).slice(0,10)+'…'):('收窗失敗：'+(result.error||result.status)));
  refresh();
});
setInterval(updateAges,1000);setInterval(()=>refresh(),5000);refresh();

/* ---------------------------------------------------------------- P60 panel */
(function () {
  const $ = (id) => document.getElementById(id);
  let targets = null;
  let paramsState = {};

  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function num(id, label, value, step) {
    return '<label class="filter"><span>' + label + '</span><input id="' + id + '" type="number" step="' + (step || 1) + '" value="' + value + '"></label>';
  }
  function sel(id, label, options) {
    return '<label class="filter"><span>' + label + '</span><select id="' + id + '">' +
      options.map((o) => '<option value="' + o[0] + '">' + esc(o[1]) + '</option>').join('') + '</select></label>';
  }
  function forceOptions() {
    const fs = (targets && targets.forces) || [];
    return fs.length ? fs.map((f) => [f.force_id, f.name + '（force ' + f.force_id + '，金 ' + f.gold + '）'])
                     : [[1, 'force 1']];
  }
  function cityOptions() {
    const cs = (targets && targets.cities) || [];
    return cs.length ? cs.map((c) => [c.city_id, c.name + ' (#' + c.city_id + ') @' + c.xy.join(',')])
                     : [[5, 'city 5']];
  }
  function renderParams() {
    const preset = $('cmd-preset').value;
    const box = $('cmd-params');
    let html = '';
    if (preset === 'train') {
      html += sel('p-troop', '兵種', [[0, '步兵'], [1, '騎兵'], [2, '弓兵']]);
      html += num('p-value', '訓練量 value（增量 ≈ value×0.4）', 100);
      html += num('p-extra', 'extra', 0);
    } else if (preset === 'alms') {
      html += num('p-value', 'value', 0) + num('p-extra', 'extra（施捨量）', 4);
    } else if (preset === 'rice') {
      html += sel('p-buy', '方向', [[1, '買米'], [0, '賣米']]);
      html += num('p-value', '數量 value', 1000) + num('p-extra', 'extra', 0);
    } else if (preset === 'build') {
      const bt = (targets && targets.build_types) || {};
      html += sel('p-build', '建築', Object.keys(bt).map((k) => [k, bt[k]]));
      html += sel('p-city', '掛在哪座城（value）', cityOptions());
      html += num('p-x', '座標 X', 0) + num('p-y', '座標 Y', 0);
      html += num('p-extra', '花費金 extra', 2000);
      html += '<button id="p-pick" class="secondary small-btn" type="button">自動挑城旁空地</button>';
    } else if (preset === 'personnel') {
      html += sel('p-sub', '子類型', [[0, '普通錄用'], [1, '接納仕官'], [2, '解雇武將'], [5, '加增武將']]);
      html += num('p-target', '武將 id（target）', 1);
    } else if (preset === 'phaseend') {
      html += '<p class="small dim">回合結束命令：實測回執 rc=1 但主機未採用，保留供研究。</p>';
    }
    box.innerHTML = html;
    const pick = $('p-pick');
    if (pick) {
      pick.onclick = async () => {
        const prefix = $('cmd-target').value;
        const cid = Number($('p-city').value);
        const city = ((targets && targets.cities) || []).find((c) => c.city_id === cid);
        const force = Number($('cmd-force').value);
        if (!city) return;
        const res = await fetch('/api/command/free-cells?prefix=' + encodeURIComponent(prefix) +
                                '&x=' + city.xy[0] + '&y=' + city.xy[1] + '&force=' + force);
        const data = await res.json();
        if (data.ok && data.cells && data.cells.length) {
          $('p-x').value = data.cells[0][0]; $('p-y').value = data.cells[0][1];
          setStatus('已挑選空地 (' + data.cells[0].join(',') + ')');
        } else { setStatus('挑不到空地：' + (data.error || '未知')); }
      };
    }
    updateSummary();
  }
  function setStatus(text) { $('cmd-status').textContent = text; }
  function updateSummary() {
    const preset = $('cmd-preset').value;
    const force = $('cmd-force').value;
    const fname = ((targets && targets.forces) || []).find((f) => String(f.force_id) === String(force));
    let s = '<strong>' + esc(fname ? fname.name : ('force ' + force)) + '</strong> ／ ' + esc(preset);
    const v = (id) => { const el = $(id); return el ? el.value : ''; };
    if (preset === 'train') s += ' ／ ' + ['步兵', '騎兵', '弓兵'][Number(v('p-troop'))] + ' × value ' + v('p-value');
    if (preset === 'rice') s += ' ／ ' + (v('p-buy') === '1' ? '買米' : '賣米') + ' × ' + v('p-value');
    if (preset === 'build') s += ' ／ 建築 ' + v('p-build') + ' @(' + v('p-x') + ',' + v('p-y') + ') 城 ' + v('p-city') + ' 金 ' + v('p-extra');
    if (preset === 'personnel') s += ' ／ 武將 ' + v('p-target');
    $('cmd-summary').innerHTML = s;
  }
  async function loadTargets() {
    setStatus('讀取目標與勢力…');
    try {
      const res = await fetch('/api/command/targets');
      targets = await res.json();
      const tsel = $('cmd-target');
      tsel.innerHTML = (targets.targets || []).map((t) =>
        '<option value="' + t.prefix + '">' + esc(t.label) + (t.alive ? ' · 在線' : ' · 離線') + '</option>').join('');
      const fsel = $('cmd-force');
      fsel.innerHTML = forceOptions().map((o) => '<option value="' + o[0] + '">' + esc(o[1]) + '</option>').join('');
      $('cmd-phase').textContent = '目前階段：' + (targets.phase_text || '未知') + '（phase=' + targets.phase + '）';
      renderParams();
      setStatus('目標已就緒。' + (targets.phase === 1 ? '現在就在內政階段。' : '現在不是內政階段，送出後會排隊等下一次內政。'));
    } catch (e) { setStatus('讀取失敗：' + e); }
  }
  function jobParams() {
    const preset = $('cmd-preset').value;
    const v = (id) => { const el = $(id); return el ? el.value : null; };
    const p = { prefix: $('cmd-target').value, preset: preset, actor: Number($('cmd-force').value) };
    if (preset === 'train') { p.troop = Number(v('p-troop')); p.value = Number(v('p-value')); p.extra = Number(v('p-extra')); }
    if (preset === 'alms') { p.value = Number(v('p-value')); p.extra = Number(v('p-extra')); }
    if (preset === 'rice') { p.buy = Number(v('p-buy')); p.value = Number(v('p-value')); p.extra = Number(v('p-extra')); }
    if (preset === 'build') { p.build_type = Number(v('p-build')); p.city = Number(v('p-city')); p.x = Number(v('p-x')); p.y = Number(v('p-y')); p.extra = Number(v('p-extra')); }
    if (preset === 'personnel') { p.subtype = Number(v('p-sub')); p.target_id = Number(v('p-target')); }
    return p;
  }
  async function send() {
    const payload = jobParams();
    setStatus('送出中…');
    $('cmd-send').disabled = true;
    try {
      const res = await fetch('/api/command/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await res.json();
      if (!data.ok) { setStatus('失敗：' + (data.error || '未知')); }
      else {
        setStatus(data.job.status === 'queued' ? '已排隊：等下一次內政階段送出。' : '已送出，等待回執…');
      }
      refreshJobs();
    } catch (e) { setStatus('送出失敗：' + e); }
    finally { $('cmd-send').disabled = false; }
  }
  function jobLine(j) {
    const cls = j.status === 'fired' ? 'ok' : (j.status === 'error' || j.status === 'send_failed' ? 'err' : 'wait');
    let detail = '';
    if (j.receipt) {
      const r = j.receipt;
      detail = 'rc=' + r.rc + ' kind=' + r.kind + ' sub=' + r.subtype +
        ' actor=' + r.actor + ' 值=' + [r.f18, r.f1c, r.f20].join('/') +
        ' 送出時 phase=' + r.phase_at_send + ' 閘門=' + r.gate_before + '/' + r.gate_after;
    } else if (j.error) { detail = j.error; }
    else { detail = '等待內政階段…'; }
    return '<li class="cmd-job"><span class="pill ' + cls + '">' + esc(j.status) + '</span>' +
      '<strong>' + esc(j.preset) + '</strong><span class="dim">' + esc(j.prefix) + '</span>' +
      '<span class="dim">' + j.waited + 's</span><span>' + esc(detail) + '</span></li>';
  }
  async function refreshJobs() {
    try {
      const res = await fetch('/api/command/jobs');
      const data = await res.json();
      const box = $('cmd-jobs');
      if (!data.jobs || !data.jobs.length) { box.innerHTML = '<li class="dim">尚無指令。</li>'; return; }
      box.innerHTML = data.jobs.map(jobLine).join('');
    } catch (e) { /* ignore */ }
  }
  document.addEventListener('DOMContentLoaded', () => {
    if (!$('cmd-send')) return;
    $('cmd-refresh').onclick = loadTargets;
    $('cmd-preset').onchange = renderParams;
    $('cmd-force').onchange = updateSummary;
    $('cmd-send').onclick = send;
    $('cmd-params').addEventListener('change', updateSummary);
    $('cmd-params').addEventListener('input', updateSummary);
    loadTargets();
    setInterval(refreshJobs, 3000);
  });
})();
