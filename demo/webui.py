"""本地 Web GUI：用标准库 http.server 起一个只监听回环地址的页面，浏览器即界面。

选择 Web UI 的原因：这台机器的 Python 缺 _tkinter，且浏览器界面更容易做出
类似 HandShaker 的侧边栏 / 标签页 / 传输队列布局。若以后换成原生窗口，
engine.snapshot() 与 engine.action() 就是现成的接口。
"""
from __future__ import annotations

import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Handover Demo — HandShaker macOS 客户端模拟</title>
<style>
:root{--bg:#f5f6f8;--panel:#fff;--line:#e3e6ea;--txt:#1d2129;--sub:#6b7280;
--accent:#2f6feb;--accent-soft:#eaf1ff;--ok:#18a058;--warn:#d97706;--err:#d03050;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}
header{height:52px;background:var(--panel);border-bottom:1px solid var(--line);
display:flex;align-items:center;gap:14px;padding:0 18px;position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0;font-weight:600}
.pill{font-size:11px;padding:3px 9px;border-radius:20px;background:#eef0f3;color:var(--sub)}
.pill.on{background:#e6f7ee;color:var(--ok)}.pill.wait{background:#fff3e0;color:var(--warn)}
.pill.bad{background:#fdeaf0;color:var(--err)}
.spacer{flex:1}.muted{color:var(--sub)}
.app{display:flex;gap:14px;padding:14px;align-items:flex-start}
aside{width:300px;flex:none;display:flex;flex-direction:column;gap:12px}
main{flex:1;min-width:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.card h2{font-size:12px;margin:0 0 10px;color:var(--sub);font-weight:600;
text-transform:uppercase;letter-spacing:.5px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:#fff;
color:var(--txt);border-radius:6px;padding:5px 10px}
button:hover{border-color:var(--accent);color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{opacity:.9;color:#fff}button:disabled{opacity:.45;cursor:not-allowed}
button.danger{color:var(--err)}
input[type=text],input[type=number],textarea{font:inherit;border:1px solid var(--line);
border-radius:6px;padding:6px 8px;width:100%;background:#fff;color:var(--txt)}
.row{display:flex;gap:6px;align-items:center}.row>*{min-width:0}
.dev{border:1px solid var(--line);border-radius:8px;padding:8px;margin-bottom:6px;
display:flex;justify-content:space-between;align-items:center;gap:8px}
.dev .nm{font-weight:600;font-size:12px}.dev .meta{font-size:11px;color:var(--sub)}
.badge{font-size:10px;padding:1px 6px;border-radius:4px;background:var(--accent-soft);color:var(--accent)}
.tabs{display:flex;gap:4px;margin-bottom:10px;border-bottom:1px solid var(--line)}
.tab{padding:7px 14px;border:none;background:none;border-bottom:2px solid transparent;color:var(--sub)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
.toolbar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.crumb{font-size:12px;color:var(--sub);margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:600;font-size:11px}
tr.sel{background:var(--accent-soft)}tr:hover{background:#f8f9fb}
.bar{height:6px;background:#eef0f3;border-radius:4px;overflow:hidden;min-width:90px}
.bar>i{display:block;height:100%;background:var(--accent)}
.qr{display:grid;gap:0;justify-content:center;margin:8px 0;line-height:0}
.qr i{width:5px;height:5px;display:block}.qr i.b{background:#111}.qr i.w{background:#fff}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}
.hidden{display:none!important}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;
align-items:center;justify-content:center;z-index:20}
.modal{background:#fff;border-radius:12px;padding:20px;width:360px;box-shadow:0 12px 40px rgba(0,0,0,.2)}
.modal h3{margin:0 0 8px;font-size:15px}.modal p{color:var(--sub);margin:0 0 16px}
.toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#1d2129;
color:#fff;padding:9px 16px;border-radius:8px;font-size:12px;z-index:30}
.toast.bad{background:var(--err)}
.empty{padding:26px;text-align:center;color:var(--sub)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kv{font-size:11px;color:var(--sub)}.kv b{color:var(--txt)}
ul.cmd{columns:2;font-size:11px;color:var(--sub);padding-left:18px;margin:6px 0}
</style>
</head>
<body>
<header>
  <h1>Handover Demo</h1>
  <span class="pill" id="stage">未连接</span>
  <span class="mono muted" id="ver"></span>
  <span class="spacer"></span>
  <span class="mono muted" id="hb"></span>
  <button onclick="doDisconnect()">断开</button>
</header>

<div class="app">
<aside>
  <div class="card"><h2>设备</h2>
    <div id="devices"></div>
    <div class="row" style="margin-top:8px">
      <input type="text" id="mHost" placeholder="IP / 主机" style="flex:2">
      <input type="number" id="mPort" placeholder="端口" style="flex:1">
    </div>
    <div class="row" style="margin-top:6px">
      <button class="primary" style="flex:1" onclick="manualConnect()">连接</button>
      <button onclick="pollOnce()">刷新</button>
    </div>
  </div>

  <div class="card"><h2>模拟手机</h2>
    <div class="kv">监听端口 <b id="pPort">-</b> · 回环地址</div>
    <label class="row" style="margin-top:8px;font-size:12px">
      <input type="checkbox" id="lockChk" style="width:auto" onchange="setLocked(this.checked)">
      模拟锁屏（握手返回 locked）
    </label>
    <div class="row" style="margin-top:8px">
      <button onclick="post('reseed')">补回示例文件</button>
    </div>
  </div>

  <div class="card"><h2>连接二维码</h2>
    <div id="qr"></div>
    <div class="mono" id="qrPayload" style="word-break:break-all;font-size:10px"></div>
  </div>

  <div class="card"><h2>能力</h2>
    <div class="kv" id="caps"></div>
  </div>
</aside>

<main>
  <div class="card">
    <div class="tabs">
      <button class="tab active" data-tab="files" onclick="switchTab('files')">文件</button>
      <button class="tab" data-tab="clip" onclick="switchTab('clip')">剪贴板</button>
      <button class="tab" data-tab="transfer" onclick="switchTab('transfer')">传输</button>
      <button class="tab" data-tab="log" onclick="switchTab('log')">协议日志</button>
      <button class="tab" data-tab="about" onclick="switchTab('about')">关于</button>
    </div>

    <div id="tab-files">
      <div class="toolbar">
        <button onclick="goUp()">上级</button>
        <button onclick="doMkdir()">新建文件夹</button>
        <label class="row" style="gap:4px">
          <input type="file" id="fileInput" style="display:none" onchange="doUpload(this)">
          <button onclick="document.getElementById('fileInput').click()">上传文件</button>
        </label>
        <button onclick="doDownload()">下载</button>
        <button onclick="doRename()">重命名</button>
        <button class="danger" onclick="doDelete()">删除（回收站）</button>
        <button onclick="post('list_dir',{path:curPath})">刷新</button>
      </div>
      <div class="crumb" id="crumb">/</div>
      <table><thead><tr><th style="width:28px"></th><th>名称</th>
        <th style="width:90px">大小</th><th style="width:140px">修改时间</th></tr></thead>
        <tbody id="fileRows"></tbody></table>
      <div class="empty hidden" id="fileEmpty">未连接，请先选择设备并信任这台电脑</div>
    </div>

    <div id="tab-clip" class="hidden">
      <div class="grid2">
        <textarea id="clipText" rows="4" placeholder="输入文字，发送到手机剪贴板"></textarea>
        <div class="row" style="align-items:flex-start">
          <button class="primary" onclick="post('clipboard_post',{text:document.getElementById('clipText').value})">发送到手机</button>
          <button onclick="post('clipboard_clear')">清空</button>
        </div>
      </div>
      <h2 style="margin-top:14px">手机剪贴板</h2>
      <div id="clipList"></div>
    </div>

    <div id="tab-transfer" class="hidden"><table>
      <thead><tr><th>类型</th><th>文件</th><th>进度</th><th>状态</th><th></th></tr></thead>
      <tbody id="transferRows"></tbody></table>
      <div class="empty hidden" id="transferEmpty">暂无传输任务</div>
    </div>

    <div id="tab-log" class="hidden"><table>
      <thead><tr><th style="width:80px">时间</th><th style="width:30px">方向</th>
      <th style="width:180px">命令</th><th>数据</th></tr></thead>
      <tbody id="logRows"></tbody></table></div>

    <div id="tab-about" class="hidden">
      <p><b>这是什么</b>：用 Python 模拟 HandShaker macOS 客户端的 GUI demo。
      界面通过本地 HTTP 接口驱动一个真正的 TCP 客户端，客户端与「模拟手机」
      通过 SSP-like 帧协议通信（控制面 JSON + session_id 裸流数据面）。</p>
      <p class="muted">真实 HandShaker 的控制面是 Protobuf，帧头与密钥交换细节尚未
      静态分析确认（见 doc/06）。因此本 demo 不能直接连官方安卓端；后续接真实设备时
      需要替换编解码层。当前可复用的部分是架构、状态机与交互流程。</p>
      <p><b>已实现的 SSP 能力</b>：两轮握手与信任、心跳、设备信息、目录浏览、
      新建/重命名/删除（回收站）、分块上传下载 + MD5 校验 + 取消、
      剪贴板双向同步与变更推送、文件变更推送。</p>
      <p><b>SSP 的 41 个请求类型</b>（左侧为协议原名，★ 表示 demo 已覆盖）：</p>
      <ul class="cmd" id="cmdList"></ul>
    </div>
  </div>
</main>
</div>

<div id="modal" class="modal-bg hidden"><div class="modal">
  <h3>手机端授权</h3>
  <p>模拟手机弹出信任对话框：<b id="trustDevice"></b> 请求连接。<br>
  真实 HandShaker 中，用户需在手机上点「信任」；此处对应 SSPHandShakeResponse02
  的 result 字段（ok / locked / needauth / failed）。</p>
  <div class="row" style="justify-content:flex-end">
    <button class="danger" onclick="doPair('NO')">拒绝</button>
    <button onclick="doPair('ONCE')">仅此一次</button>
    <button class="primary" onclick="doPair('ALWAYS')">始终信任</button>
  </div>
</div></div>
<div id="toast" class="toast hidden"></div>

<script>
let state=null, curPath='/', selected=new Set(), tab='files', trustVisible=false;
const $=id=>document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtSize(n){if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';return (n/1048576).toFixed(1)+' MB';}
function fmtTime(t){if(!t)return '-';const d=new Date(t*1000);return d.toLocaleString('zh-CN',{hour12:false});}
function toast(msg,bad){const e=$('toast');e.textContent=msg;e.className='toast'+(bad?' bad':'');setTimeout(()=>e.classList.add('hidden'),2600);}
async function post(cmd,args={}){
  let j;
  try{const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({cmd,args})});j=await r.json();}
  catch(e){toast('请求失败: '+e,true);return null;}
  if(!j.ok){toast(j.error||'操作失败',true);} 
  state=j.state;render();return j;
}
async function pollOnce(){try{const r=await fetch('/api/state');state=await r.json();render();}catch(e){}}
function switchTab(t){tab=t;document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===t));
  ['files','clip','transfer','log','about'].forEach(x=>$('tab-'+x).classList.toggle('hidden',x!==t));}
function connectDev(el){post('connect',{host:el.dataset.host,port:parseInt(el.dataset.port)});}
function manualConnect(){const h=$('mHost').value.trim()||'127.0.0.1';const p=parseInt($('mPort').value||state?.phone?.port||0);
  post('connect',{host:h,port:p});}
function doDisconnect(){post('disconnect');}
function doPair(t){post('pair',{trust:t});trustVisible=false;}
function setLocked(v){post('set_locked',{locked:v});}
function goUp(){if(curPath==='/')return;const p=curPath.replace(/\/$/,'').split('/');p.pop();
  post('list_dir',{path:'/'+(p.filter(Boolean).join('/'))});}
function doMkdir(){const n=prompt('新建文件夹名称');if(n)post('mkdir',{name:n});}
function doRename(){if(selected.size!==1){toast('请选中一个文件',true);return;}
  const n=prompt('新名称');if(n)post('rename',{path:[...selected][0],new_name:n});}
function doDelete(){if(!selected.size){toast('请先选择文件',true);return;}
  if(confirm('把选中的 '+selected.size+' 项移入回收站？'))post('delete',{paths:[...selected]});}
function doDownload(){const items=[...selected].filter(p=>{
  const e=state?.listing?.entries?.find(x=>x.path===p);return e&&!e.is_dir;});
  if(!items.length){toast('请选中文件（非目录）',true);return;}
  items.forEach(p=>post('download',{path:p}));switchTab('transfer');}
function doUpload(input){const f=input.files[0];if(!f)return;
  if(f.size>8*1024*1024){toast('演示限制：单文件不超过 8 MB',true);input.value='';return;}
  const rd=new FileReader();rd.onload=()=>{
    const b64=String(rd.result).split(',')[1]||'';
    post('upload',{name:f.name,content_b64:b64});input.value='';};
  rd.readAsDataURL(f);}

function render(){
  if(!state)return;
  const c=state.connection,q=state.qr;
  const labels={disconnected:'未连接',connected:'已连接',need_trust:'等待手机授权',
    paired:'已连接 · 已信任',rejected:'被拒绝',locked:'手机锁屏',dead:'连接中断'};
  const cls={paired:'on',connected:'wait',need_trust:'wait',locked:'wait',rejected:'bad',dead:'bad'};
  $('stage').textContent=labels[c.stage]||c.stage;$('stage').className='pill '+(cls[c.stage]||'');
  $('ver').textContent='协议 '+(c.protocol_version||'-')+' · demo '+state.versions.app;
  $('hb').textContent=c.last_heartbeat?('心跳 '+new Date(c.last_heartbeat*1000).toLocaleTimeString('zh-CN',{hour12:false})):'';
  $('pPort').textContent=state.phone.port;
  $('lockChk').checked=state.phone.locked;
  $('caps').innerHTML='mDNS '+(state.capabilities.zeroconf?'可用':'不可用')+
    ' · 二维码 '+(state.capabilities.qrcode?'可用':'不可用')+
    (state.capabilities.zeroconf_error?('<br><span class="mono">'+esc(state.capabilities.zeroconf_error)+'</span>'):'');

  // 设备列表
  $('devices').innerHTML=state.devices.map(d=>
    '<div class="dev"><div><div class="nm">'+esc(d.name)+' <span class="badge">'+esc(d.source)+'</span></div>'+
    '<div class="meta mono">'+esc(d.host)+':'+d.port+'</div></div>'+
    '<button class="primary" data-host="'+esc(d.host)+'" data-port="'+d.port+'" onclick="connectDev(this)">连接</button></div>').join('');

  // 二维码
  $('qrPayload').textContent=q.payload||'';
  if(q.matrix&&q.matrix.length){
    const n=q.matrix.length;
    $('qr').innerHTML='<div class="qr" style="grid-template-columns:repeat('+n+',5px)">'+
      q.matrix.map(row=>row.map(v=>'<i class="'+(v?'b':'w')+'"></i>').join('')).join('')+'</div>';
  }else{$('qr').innerHTML='<div class="empty">二维码不可用</div>';}

  // 信任弹窗
  const need=c.stage==='need_trust';
  $('modal').classList.toggle('hidden',!need);
  if(need){$('trustDevice').textContent=c.device?.device_name||'未知设备';}
  // 文件
  curPath=state.current_path||'/';$('crumb').textContent=curPath;
  const entries=state.listing?.entries||[];
  const paired=c.stage==='paired';
  $('fileEmpty').classList.toggle('hidden',paired);
  $('fileRows').innerHTML=entries.map(e=>{
    const p=e.path,sel=selected.has(p);
    return '<tr class="'+(sel?'sel':'')+'" data-path="'+esc(p)+'" onclick="toggleRow(this)">'+
      '<td><input type="checkbox" style="width:auto" '+(sel?'checked':'')+' onclick="event.stopPropagation();toggleRow(this.parentNode.parentNode)"></td>'+
      '<td>'+(e.is_dir?'📁 ':'📄 ')+'<a href="#" class="open" data-path="'+esc(p)+'" data-dir="'+(e.is_dir?'1':'0')+'">'+esc(e.name)+'</a></td>'+
      '<td>'+(e.is_dir?'-':fmtSize(e.size))+'</td><td>'+fmtTime(e.mtime)+'</td></tr>';}).join('');
  // 剪贴板
  $('clipList').innerHTML=(state.clipboard||[]).length?state.clipboard.map(i=>
    '<div class="card" style="margin-bottom:6px"><div class="mono">'+esc(i.text)+'</div>'+
    '<div class="kv">'+fmtTime(Math.floor(i.ts/1000))+'</div></div>').join(''):'<div class="empty">手机剪贴板为空</div>';
  // 传输
  const trs=state.transfers||[];
  $('transferEmpty').classList.toggle('hidden',trs.length>0);
  $('transferRows').innerHTML=trs.map(t=>{
    const pct=t.size?Math.min(100,Math.round(t.transferred/t.size*100)):(t.status==='done'?100:0);
    const st={running:'进行中',done:'完成',cancelled:'已取消',error:'错误'}[t.status]||t.status;
    const dl=t.status==='done'&&t.kind==='download'?
      '<a href="/api/download?name='+encodeURIComponent(t.name)+'">保存到电脑</a> ':'';
    const cancel=t.status==='running'?'<button onclick="post(\'cancel\',{session_id:'+t.id+'})">取消</button>':'';
    return '<tr><td>'+(t.kind==='upload'?'上传':'下载')+'</td><td>'+esc(t.name)+
      '<div class="kv">#'+t.id+' '+fmtSize(t.transferred)+' / '+fmtSize(t.size)+'</div></td>'+
      '<td><div class="bar"><i style="width:'+pct+'%"></i></div><div class="kv">'+pct+'%</div></td>'+
      '<td>'+st+(t.error?' <span class="pill bad">'+esc(t.error)+'</span>':'')+'</td><td>'+dl+cancel+'</td></tr>';}).join('');
  // 日志
  $('logRows').innerHTML=(state.log||[]).slice().reverse().map(l=>
    '<tr><td class="mono">'+esc(l.ts)+'</td><td>'+esc(l.dir)+'</td>'+
    '<td class="mono">'+esc(l.cmd)+'</td><td class="mono">'+esc(l.brief)+'</td></tr>').join('');
  // 命令清单
  if(!$('cmdList').children.length){
    const covered=new Set(['HEART_BEAT_REQUEST','GET_DEVICE_INFO_REQUEST','GET_DIR_FILES_REQUEST',
      'GET_CREATE_FOLDER_REQUEST','GET_RENAME_FILE_REQUEST','GET_DELETE_FILE_REQUEST',
      'GET_DOWNLOAD_FILE_REQUEST','GET_UPLOAD_FILE_REQUEST_HEADER','GET_CLIPBOARD_REQUEST',
      'POST_CLIPBOARD_REQUEST','CLEAR_CLIPBOARD_REQUEST','CLIPBOARD_CHANGE',
      'HANDSHAKE_REQUEST_01','HANDSHAKE_REQUEST_02','QUIT_REQUEST','CANCEL_REQUEST','FILE_CHANGE']);
    $('cmdList').innerHTML=state.ssp_request_types.map(x=>'<li>'+(covered.has(x)?'★ ':'')+esc(x)+'</li>').join('');
  }
}
function toggleRow(tr){const p=tr.dataset.path;if(selected.has(p))selected.delete(p);else selected.add(p);render();}
function openEntry(p,isDir){if(isDir){selected.clear();post('list_dir',{path:p});}else{selected=new Set([p]);render();}}
document.addEventListener('click',function(e){var a=e.target.closest('a.open');if(a){e.preventDefault();openEntry(a.dataset.path,a.dataset.dir==='1');}});
setInterval(pollOnce,900);pollOnce();
</script>
</body></html>
"""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # 保持控制台安静，日志由 UI 里的「协议日志」标签页承载

        def _send(self, body: bytes, ctype: str, status: int = 200,
                  extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, obj, status: int = 200) -> None:
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", status)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                self._json(engine.snapshot())
                return
            if parsed.path == "/api/download":
                qs = urllib.parse.parse_qs(parsed.query)
                name = os.path.basename((qs.get("name") or [""])[0])
                safe = name.replace('"', "").replace("\r", "").replace("\n", "")
                target = (engine.downloads / safe).resolve()
                if not safe or engine.downloads.resolve() not in target.parents:
                    self._json({"error": "文件不存在"}, 404)
                    return
                if not target.is_file():
                    self._json({"error": "文件不存在"}, 404)
                    return
                self._send(target.read_bytes(), "application/octet-stream", 200, {
                    "Content-Disposition": f'attachment; filename="{safe}"',
                })
                return
            self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/action":
                self._json({"error": "not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                self._json({"ok": False, "error": f"请求格式错误: {exc}",
                            "state": engine.snapshot()}, 400)
                return
            try:
                result = engine.action(str(payload.get("cmd", "")),
                                       payload.get("args") or {})
                self._json({"ok": True, "result": result, "state": engine.snapshot()})
            except Exception as exc:
                self._json({"ok": False, "error": str(exc),
                            "state": engine.snapshot()})

    return Handler


def serve(engine, host: str = "127.0.0.1", port: int = 0):
    """启动本地 Web GUI，返回 (server, url)。只监听回环地址。"""
    server = _Server((host, port), make_handler(engine))
    url = f"http://{host}:{server.server_address[1]}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="webui")
    thread.start()
    return server, url
