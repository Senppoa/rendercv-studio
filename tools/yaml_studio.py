#!/usr/bin/env python3
"""RenderCV YAML Studio: local web editor with real RenderCV preview.

Usage:
    python tools/yaml_studio.py --root examples
    python tools/yaml_studio.py --root /path/to/rendercv-files --port 8642

The server binds to localhost only. YAML files are edited in the browser and
rendered by the installed RenderCV executable, so the preview is faithful to
the final PDF rather than an approximate HTML recreation.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MAX_BODY = 4 * 1024 * 1024


def clean_log(value: str) -> str:
    return ANSI_ESCAPE.sub("", value).strip()


def resolve_rendercv() -> str | None:
    configured = os.environ.get("RENDERCV_BIN")
    candidates = [configured, shutil.which("rendercv"), str(Path.home() / ".local/bin/rendercv")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def studio_page() -> str:
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>RenderCV YAML Studio</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/eclipse.min.css">
  <style>
    :root { --ink:#17283b; --muted:#697b8e; --blue:#1b57a5; --blue-dark:#0f3567; --line:#d9e2ec; --paper:#f3f6fa; --green:#18794e; --red:#b42318; }
    * { box-sizing:border-box; }
    html,body { margin:0; height:100%; color:var(--ink); font-family:Inter,"Noto Sans CJK SC","Microsoft YaHei",sans-serif; }
    body { display:flex; flex-direction:column; background:#e9eef4; }
    .topbar { min-height:62px; padding:10px 18px; display:flex; align-items:center; gap:12px; background:#fff; border-bottom:1px solid var(--line); box-shadow:0 1px 8px #20344b12; z-index:2; }
    .brand { display:flex; align-items:baseline; gap:10px; white-space:nowrap; }
    .brand strong { font-size:17px; letter-spacing:.2px; }
    .brand span { color:var(--muted); font-size:12px; }
    .file-picker { display:flex; align-items:center; gap:8px; margin-left:12px; }
    select,button { font:inherit; }
    select { min-width:210px; padding:7px 10px; color:var(--ink); background:#fff; border:1px solid #c9d5e1; border-radius:6px; }
    button { border:1px solid #c2cfdd; border-radius:6px; padding:7px 12px; color:var(--blue-dark); background:#fff; cursor:pointer; white-space:nowrap; }
    button:hover { border-color:var(--blue); background:#f5f8fc; }
    button.primary { color:#fff; background:var(--blue); border-color:var(--blue); }
    button.primary:hover { background:#164986; }
    .toolbar { margin-left:auto; display:flex; align-items:center; gap:8px; }
    .auto { display:flex; align-items:center; gap:5px; color:var(--muted); font-size:12px; white-space:nowrap; }
    .auto input { accent-color:var(--blue); }
    main { display:grid; grid-template-columns:minmax(410px,46%) minmax(420px,1fr); min-height:0; flex:1; }
    .editor-panel,.preview-panel { min-width:0; min-height:0; display:flex; flex-direction:column; }
    .editor-panel { background:#fafbfd; border-right:1px solid var(--line); }
    .preview-panel { background:var(--paper); }
    .panel-head { height:42px; padding:0 14px; display:flex; align-items:center; gap:10px; flex:none; border-bottom:1px solid var(--line); background:#fff; }
    .panel-head strong { font-size:13px; }
    .panel-head small { color:var(--muted); font-size:11px; }
    .editor-wrap { flex:1; min-height:0; position:relative; }
    #source { width:100%; height:100%; padding:15px; border:0; outline:0; resize:none; color:#18324b; background:#fbfcfe; font:13px/1.6 ui-monospace,SFMono-Regular,Consolas,"Noto Sans Mono",monospace; tab-size:2; }
    .CodeMirror { height:100%; font:13px/1.6 ui-monospace,SFMono-Regular,Consolas,"Noto Sans Mono",monospace; }
    .CodeMirror-gutters { border-right:1px solid #dbe4ed; background:#f3f6fa; }
    .CodeMirror-foldgutter { width:12px; }
    .editor-foot { padding:7px 14px; color:var(--muted); font-size:11px; border-top:1px solid var(--line); background:#fff; }
    .preview-tools { margin-left:auto; display:flex; gap:5px; }
    .view-tab { padding:4px 9px; font-size:11px; }
    .view-tab.active { color:#fff; border-color:var(--blue); background:var(--blue); }
    #preview { flex:1; min-height:0; overflow:auto; padding:20px; display:flex; justify-content:center; align-items:flex-start; }
    #pdf-frame { width:min(100%,794px); height:calc(100vh - 135px); min-height:680px; border:0; background:#fff; box-shadow:0 6px 24px #24384d2b; }
    #pages { width:min(100%,794px); display:none; flex-direction:column; gap:18px; align-items:center; }
    #pages img { width:100%; height:auto; background:#fff; box-shadow:0 6px 24px #24384d2b; }
    #empty { max-width:440px; margin:110px auto; color:var(--muted); text-align:center; line-height:1.7; }
    #error { display:none; width:min(100%,780px); color:var(--red); background:#fff5f4; border:1px solid #f3c8c4; border-radius:8px; padding:14px; white-space:pre-wrap; font:12px/1.6 ui-monospace,monospace; }
    #status { min-width:110px; color:var(--muted); font-size:11px; text-align:right; }
    #status.ok { color:var(--green); } #status.bad { color:var(--red); }
    .busy { opacity:.58; pointer-events:none; }
    @media (max-width:900px) {
      .topbar { flex-wrap:wrap; }
      .brand { width:100%; }
      .file-picker { margin-left:0; }
      .toolbar { margin-left:0; }
      main { grid-template-columns:1fr; grid-template-rows:minmax(330px,45vh) minmax(470px,1fr); }
      .editor-panel { border-right:0; border-bottom:1px solid var(--line); }
      #pdf-frame { min-height:600px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><strong>RenderCV YAML Studio</strong><span>可读的 YAML 编辑 · 真实 PDF 预览</span></div>
    <div class="file-picker"><label for="file">简历：</label><select id="file"></select></div>
    <div class="toolbar">
      <label class="auto"><input id="auto" type="checkbox" checked> 自动渲染</label>
      <button id="render" class="primary">▶ 渲染预览</button>
      <button id="save">保存 YAML</button>
      <button id="downloadYaml">下载 YAML</button>
      <button id="downloadPdf" disabled>下载 PDF</button>
    </div>
  </header>
  <main>
    <section class="editor-panel">
      <div class="panel-head"><strong>YAML 内容</strong><small id="path"></small></div>
      <div class="editor-wrap"><textarea id="source" spellcheck="false" aria-label="YAML source"></textarea></div>
      <div class="editor-foot">Ctrl/Cmd + S 保存 · Ctrl/Cmd + Enter 渲染 · 修改后自动保存为浏览器草稿</div>
    </section>
    <section class="preview-panel">
      <div class="panel-head">
        <strong>RenderCV 预览</strong><span id="status">准备就绪</span>
        <div class="preview-tools"><button class="view-tab active" data-view="pdf">PDF</button><button class="view-tab" data-view="pages">页面图</button></div>
      </div>
      <div id="preview">
        <iframe id="pdf-frame" title="PDF preview"></iframe>
        <div id="pages"></div>
        <div id="empty">选择左侧 YAML 后点击“渲染预览”。<br>预览由本机 RenderCV 生成，和最终导出的 PDF 保持一致。</div>
        <pre id="error"></pre>
      </div>
    </section>
  </main>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/yaml/yaml.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/foldcode.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/foldgutter.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/indent-fold.min.js"></script>
  <script>
    const $ = id => document.getElementById(id);
    const select = $('file'), source = $('source'), status = $('status');
    let editor = null, current = '', currentPdfUrl = '', renderTimer = null, requestNo = 0;

    function text() { return editor ? editor.getValue() : source.value; }
    function setText(value) { if (editor) editor.setValue(value); else source.value = value; }
    function setStatus(value, kind='') { status.textContent = value; status.className = kind; }
    function draftKey() { return 'rendercv-yaml-studio:' + current; }

    function initEditor() {
      if (window.CodeMirror) {
        editor = CodeMirror.fromTextArea(source, {
          mode:'yaml', theme:'eclipse', lineNumbers:true, lineWrapping:false,
          foldGutter:true, gutters:['CodeMirror-linenumbers','CodeMirror-foldgutter'],
          tabSize:2, indentUnit:2, autofocus:true
        });
        editor.on('change', changed);
      } else source.addEventListener('input', changed);
    }
    function changed() {
      localStorage.setItem(draftKey(), text());
      if (!$('auto').checked) return;
      clearTimeout(renderTimer);
      renderTimer = setTimeout(render, 1000);
      setStatus('等待渲染…');
    }
    async function api(path, options={}) {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.error || data.log || '请求失败');
      return data;
    }
    async function loadFiles() {
      const data = await api('/api/files');
      select.innerHTML = '';
      data.files.forEach(name => { const o=document.createElement('option'); o.value=name; o.textContent=name; select.appendChild(o); });
      if (!data.files.length) { setStatus('没有 YAML 文件','bad'); return; }
      await loadFile(data.files[0]);
    }
    async function loadFile(name) {
      current = name; select.value = name; $('path').textContent = name;
      const data = await api('/api/file?name=' + encodeURIComponent(name));
      const saved = localStorage.getItem(draftKey());
      setText(saved !== null ? saved : data.content);
      if (saved !== null) setStatus('已恢复浏览器草稿');
      else setStatus('已加载');
      clearPreview();
      render();
    }
    function clearPreview() {
      $('empty').style.display='block'; $('error').style.display='none'; $('pdf-frame').style.display='none'; $('pages').style.display='none';
      $('downloadPdf').disabled=true;
      if (currentPdfUrl) { URL.revokeObjectURL(currentPdfUrl); currentPdfUrl=''; }
    }
    function bytes(b64) {
      const raw=atob(b64), out=new Uint8Array(raw.length); for(let i=0;i<raw.length;i++) out[i]=raw.charCodeAt(i); return out;
    }
    function download(data, name, type) {
      const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([data],{type})); a.download=name; a.click();
      setTimeout(()=>URL.revokeObjectURL(a.href),1000);
    }
    async function render() {
      if (!current) return;
      const id=++requestNo; $('render').classList.add('busy'); setStatus('RenderCV 渲染中…');
      try {
        const data=await api('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:current,content:text()})});
        if (id!==requestNo) return;
        if (currentPdfUrl) URL.revokeObjectURL(currentPdfUrl);
        const pdfUrl=URL.createObjectURL(new Blob([bytes(data.pdf_b64)],{type:'application/pdf'})); currentPdfUrl=pdfUrl;
        $('pdf-frame').src=pdfUrl; $('pdf-frame').style.display='block'; $('empty').style.display='none'; $('error').style.display='none';
        const pages=$('pages'); pages.innerHTML=''; data.pngs.forEach(p=>{const img=new Image(); img.src='data:image/png;base64,'+p.b64; img.alt='Rendered page '+p.number; pages.appendChild(img);});
        $('downloadPdf').disabled=false; $('downloadPdf').onclick=()=>download(bytes(data.pdf_b64),current.replace(/\.ya?ml$/i,'')+'.pdf','application/pdf');
        setStatus('渲染成功 · '+data.duration_ms+' ms','ok');
      } catch (e) {
        if (id!==requestNo) return;
        $('pdf-frame').style.display='none'; $('pages').style.display='none'; $('empty').style.display='none'; $('error').textContent=e.message; $('error').style.display='block'; setStatus('渲染失败','bad');
      } finally { $('render').classList.remove('busy'); }
    }
    async function save() {
      try { await api('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:current,content:text()})}); localStorage.removeItem(draftKey()); setStatus('YAML 已保存','ok'); await render(); }
      catch(e) { setStatus('保存失败','bad'); $('error').textContent=e.message; $('error').style.display='block'; }
    }
    select.addEventListener('change',()=>loadFile(select.value));
    $('render').addEventListener('click',render); $('save').addEventListener('click',save);
    $('downloadYaml').addEventListener('click',()=>download(text(),current,'text/yaml;charset=utf-8'));
    document.querySelectorAll('.view-tab').forEach(tab=>tab.addEventListener('click',()=>{
      document.querySelectorAll('.view-tab').forEach(t=>t.classList.remove('active')); tab.classList.add('active');
      const pages=tab.dataset.view==='pages'; $('pdf-frame').style.display=pages?'none':'block'; $('pages').style.display=pages?'flex':'none';
    }));
    document.addEventListener('keydown',e=>{
      if ((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s') { e.preventDefault(); save(); }
      if ((e.ctrlKey||e.metaKey)&&e.key==='Enter') { e.preventDefault(); render(); }
    });
    initEditor(); loadFiles().catch(e=>{setStatus('无法连接服务器','bad'); $('error').textContent=e.message; $('error').style.display='block';});
  </script>
</body>
</html>'''


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "RenderCVYAMLStudio/1.0"

    def log_message(self, _format: str, *_args) -> None:
        return

    @property
    def root(self) -> Path:
        return self.server.app_root  # type: ignore[attr-defined]

    @property
    def rendercv_bin(self) -> str | None:
        return self.server.rendercv_bin  # type: ignore[attr-defined]

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: int = 200) -> None:
        self.send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def safe_yaml_path(self, name: str) -> Path:
        candidate = Path(name)
        if candidate.name != name or candidate.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("只允许访问根目录下的 YAML 文件")
        path = (self.root / candidate).resolve()
        if path.parent != self.root or not path.is_file():
            raise ValueError("YAML 文件不存在或路径无效")
        return path

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("请求内容为空或超过 4 MB")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求格式必须是 JSON 对象")
        return data

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_bytes(200, studio_page().encode("utf-8"), "text/html; charset=utf-8")
            elif parsed.path == "/api/files":
                files = sorted(p.name for p in self.root.iterdir() if p.is_file() and p.suffix.lower() in {".yaml", ".yml"})
                self.send_json({"ok": True, "files": files})
            elif parsed.path == "/api/file":
                query = parse_qs(parsed.query)
                path = self.safe_yaml_path(query.get("name", [""])[0])
                self.send_json({"ok": True, "name": path.name, "content": path.read_text(encoding="utf-8")})
            else:
                self.send_json({"ok": False, "error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self.read_json_body()
            path = self.safe_yaml_path(str(body.get("name", "")))
            content = body.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("YAML 内容不能为空")
            if parsed.path == "/api/save":
                tmp = path.with_name(f".{path.name}.yaml-studio.tmp")
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, path)
                self.send_json({"ok": True, "name": path.name})
            elif parsed.path == "/api/render":
                self.render_yaml(path.name, content)
            else:
                self.send_json({"ok": False, "error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)

    def render_yaml(self, name: str, content: str) -> None:
        if not self.rendercv_bin:
            raise RuntimeError("找不到 rendercv。请先安装：uv tool install \"rendercv[full]\"，或设置 RENDERCV_BIN。")
        start = time.perf_counter()
        temp_yaml = None
        out_dir = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".yaml", prefix=".yaml-studio-", dir=self.root, delete=False
            ) as handle:
                handle.write(content)
                temp_yaml = Path(handle.name)
            out_dir = Path(tempfile.mkdtemp(prefix=".yaml-studio-out-", dir=self.root))
            command = [
                self.rendercv_bin,
                "render",
                str(temp_yaml),
                "--output-folder",
                str(out_dir),
                "--dont-generate-html",
                "--dont-generate-markdown",
            ]
            process = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=90)
            log = clean_log((process.stdout or "") + "\n" + (process.stderr or ""))
            if process.returncode != 0:
                raise RuntimeError(log or "RenderCV 返回失败状态")
            pdfs = sorted(out_dir.glob("*.pdf"))
            pngs = sorted(out_dir.glob("*.png"))
            if not pdfs:
                raise RuntimeError(log or "RenderCV 未生成 PDF")
            payload = {
                "ok": True,
                "name": name,
                "duration_ms": round((time.perf_counter() - start) * 1000),
                "log": log,
                "pdf_b64": base64.b64encode(pdfs[0].read_bytes()).decode("ascii"),
                "pngs": [
                    {"number": index + 1, "name": png.name, "b64": base64.b64encode(png.read_bytes()).decode("ascii")}
                    for index, png in enumerate(pngs)
                ],
            }
            self.send_json(payload)
        finally:
            if temp_yaml:
                temp_yaml.unlink(missing_ok=True)
            if out_dir:
                shutil.rmtree(out_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="RenderCV YAML Studio")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="包含 YAML 文件和 assets/ 的目录")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认只监听本机")
    parser.add_argument("--port", type=int, default=8642, help="监听端口")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"根目录不存在：{root}")
    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    server.app_root = root  # type: ignore[attr-defined]
    server.rendercv_bin = resolve_rendercv()  # type: ignore[attr-defined]
    print(f"RenderCV YAML Studio: http://{args.host}:{args.port}")
    print(f"YAML root: {root}")
    print(f"RenderCV: {server.rendercv_bin or 'not found'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
