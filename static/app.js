const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
const initData = tg?.initData || "";
let me = null, withdrawKind = "toman", withdrawals = [];
const $ = id => document.getElementById(id);
const fa = n => Number(n||0).toLocaleString("fa-IR");
async function api(path, method="GET", body=null){
  const res = await fetch(path,{method,headers:{"Content-Type":"application/json","Authorization":"tma "+initData},body:body?JSON.stringify(body):null});
  const data = await res.json().catch(()=>({detail:"خطای سرور"}));
  if(!res.ok) throw new Error(data.detail||"درخواست ناموفق بود");
  return data;
}
function toast(s){$("toast").textContent=s;$("toast").classList.add("show");setTimeout(()=>$("toast").classList.remove("show"),2600)}
function showTab(tab){
  ["wallet","referral","account"].forEach(x=>$(x+"Tab").classList.add("hidden"));
  if(tab==="home"){ $("mainView").scrollIntoView({behavior:"smooth"}); return; }
  $(tab+"Tab").classList.remove("hidden"); $(tab+"Tab").scrollIntoView({behavior:"smooth"});
}
function syncMinerVideo(active){
 const video = $("minerVideo");
 if(!video) return;
 if(active){
  if(video.classList.contains("hidden")){
   video.classList.remove("hidden");
   $("machineFallback")?.classList.add("hidden");
  }
  const playPromise = video.play();
  if(playPromise?.catch) playPromise.catch(()=>toast("اگر ویدیو پخش نشد، فایل miner.mp4 را در پوشه static آپلود کنید."));
 }else{
  video.pause();
  try{video.currentTime=0}catch(e){}
 }
 video.onerror = () => { video.classList.add("hidden"); $("machineFallback")?.classList.remove("hidden"); };
}
function render(){
  $("authView").classList.add("hidden");$("mainView").classList.remove("hidden");
  $("usernameLabel").textContent=me.username;
  $("tomanBalance").textContent=fa(me.toman_balance)+" تومان";
  $("usdtBalance").textContent=Number(me.usdt_balance).toFixed(3)+" USDT";
  $("walletToman").textContent=fa(me.toman_balance)+" تومان";
  $("walletUsdt").textContent=Number(me.usdt_balance).toFixed(3)+" USDT";
  $("myRefCode").textContent=me.referral_code;
  $("pinSetup").classList.toggle("hidden",me.has_withdrawal_pin);
  updateMining();
}
async function refresh(){me=await api("/api/me");if(me.registered){render();loadWithdrawals()}else{$("authView").classList.remove("hidden");$("mainView").classList.add("hidden")}}
async function register(){
 try{me=await api("/api/register","POST",{username:$("regUser").value,password:$("regPass").value,referral_code:$("refCode").value||null});render();toast("حساب ساخته شد")}
 catch(e){toast(e.message)}
}
async function login(){
 try{me=await api("/api/login","POST",{username:$("loginUser").value,password:$("loginPass").value});render();toast("خوش آمدید")}
 catch(e){toast(e.message)}
}
async function forgot(){
 const p=prompt("رمز جدید را وارد کنید (حداقل ۶ کاراکتر):"); if(!p)return;
 try{await api("/api/forgot-password","POST",{username:"",password:p});toast("رمز اختصاصی برنامه تغییر کرد")}
 catch(e){toast(e.message)}
}
async function changePassword(){
 try{await api("/api/password","POST",{current_password:$("oldPass").value,new_password:$("newPass").value});$("oldPass").value=$("newPass").value="";toast("رمز تغییر کرد")}
 catch(e){toast(e.message)}
}
async function setPin(){
 try{await api("/api/withdrawal-pin","POST",{pin:$("pin1").value,confirm_pin:$("pin2").value});me.has_withdrawal_pin=true;render();toast("رمز برداشت ثبت شد")}
 catch(e){toast(e.message)}
}
async function startMining(){
 try{await api("/api/mining/start","POST",{});await refresh();toast("استخراج شروع شد")}
 catch(e){toast(e.message)}
}
async function stopMining(){
 if(!confirm("با توقف دستی، پاداش کامل این دوره دریافت نمی‌شود. ادامه می‌دهید؟"))return;
 try{await api("/api/mining/stop","POST",{});await refresh();toast("دوره متوقف شد")}
 catch(e){toast(e.message)}
}
async function claimMining(){
 try{await api("/api/mining/claim","POST",{});await refresh();toast("۴۲٬۰۰۰ تومان اعتبار آزمایشی اضافه شد")}
 catch(e){toast(e.message)}
}
function updateMining(){
 const start=me.mining_started_at, due=me.mining_due_at, now=Math.floor(Date.now()/1000);
 const active=!!start && !!due && now<due, ready=!!due && now>=due;
 syncMinerVideo(active);
 $("mineBtn").classList.toggle("hidden",active||ready);
 $("stopBtn").classList.toggle("hidden",!active);
 $("claimBtn").classList.toggle("hidden",!ready);
 $("miningStatus").textContent=active?"در حال استخراج":ready?"آماده دریافت":"متوقف";
 if(active){
  const elapsed=Math.max(0,now-start), pct=Math.min(100,elapsed/86400*100), left=Math.max(0,due-now);
  $("progressBar").style.width=pct+"%";$("percentText").textContent=fa(Math.floor(pct))+"٪";
  $("timerText").textContent="زمان باقی‌مانده: "+fa(Math.floor(left/3600))+" ساعت";
 }else if(ready){$("progressBar").style.width="100%";$("percentText").textContent="۱۰۰٪";$("timerText").textContent="دوره کامل شد؛ درآمد را دریافت کنید"}
 else{$("progressBar").style.width="0%";$("percentText").textContent="۰٪";$("timerText").textContent="برای شروع آماده است"}
}
setInterval(()=>{if(me?.registered)updateMining()},1000);
function openWithdraw(kind){
 if(!me.has_withdrawal_pin){toast("ابتدا در تنظیمات حساب رمز برداشت تعیین کنید");showTab("account");return}
 withdrawKind=kind;$("withdrawForm").classList.remove("hidden");
 $("withdrawTitle").textContent=kind==="toman"?"برداشت تومانی":"برداشت تتری";
 $("destLabel").textContent=kind==="toman"?"شماره کارت":"آدرس BEP20";
 $("destination").placeholder=kind==="toman"?"شماره کارت ۱۶ رقمی":"آدرس BEP20";
 $("ownerWrap").classList.toggle("hidden",kind!=="toman");
 $("amount").value="";$("destination").value="";$("ownerName").value="";$("withdrawPin").value="";
 $("withdrawForm").scrollIntoView({behavior:"smooth"});
}
function setMax(){$("amount").value=withdrawKind==="toman"?me.toman_balance:Math.floor(me.usdt_balance*270000)}
async function submitWithdraw(){
 try{
  await api("/api/withdraw","POST",{kind:withdrawKind,amount:Number($("amount").value),destination:$("destination").value.trim(),owner_name:withdrawKind==="toman"?$("ownerName").value.trim():null,pin:$("withdrawPin").value});
  toast("درخواست آزمایشی ثبت شد");$("withdrawForm").classList.add("hidden");await refresh();
 }catch(e){toast(e.message)}
}
async function loadWithdrawals(){
 try{withdrawals=await api("/api/withdrawals");const box=$("withdrawHistory");
 if(!withdrawals.length){box.textContent="هنوز درخواستی ثبت نشده است.";return}
 box.innerHTML=withdrawals.map(w=>`<div class="history-item"><b>${w.kind==="toman"?"برداشت تومانی":"برداشت تتری"} — ${fa(w.amount)}</b><br>${w.kind==="toman"?escapeHtml(w.destination)+" ("+escapeHtml(w.owner_name||"")+")":escapeHtml(w.destination)}<br><span>${new Date(w.created_at*1000).toLocaleString("fa-IR")} · ${w.status==="pending"?"در حال بررسی":w.status==="paid_demo"?"واریز شد (نمایشی)":"لغوشده"}</span>${w.status==="pending"?`<button onclick="cancelWithdrawal(${w.id})">لغو برداشت</button>`:""}</div>`).join("");
 }catch(e){console.warn(e)}
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function cancelWithdrawal(id){try{await api(`/api/withdrawals/${id}/cancel`,"POST",{});await refresh();toast("درخواست لغو و اعتبار برگشت داده شد")}catch(e){toast(e.message)}}
async function copyRef(){try{await navigator.clipboard.writeText(me.referral_code);toast("کد دعوت کپی شد")}catch(e){toast(me.referral_code)}}
refresh().catch(e=>toast(e.message));
