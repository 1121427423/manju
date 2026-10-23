#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 out/review/video3s_refs 的参考图与提示词, 调 agnes-video-2.5-flash 出 3 秒图生视频。

为什么直连 apihub 而不是本地网关(2026-10-24 实测):
  - 网关 /v1/videos 未在端点 allowlist 里 → 404 `endpoint is not enabled on this gateway`
    (agnes/ 与 cn-agens/ 两条路由都是这个结果, 与"apihub 渲染返空体"是两回事)。
  - 直连 https://apihub.agnes-ai.com + AGNES_TOKEN_PLAN_KEY(cpk-) 实测 text 模式
    14 次轮询后 completed, 拿得到 url —— 渲染链路通。
凭据只从环境或 ~/.zshrc 读, 不落任何文件。

参考图必须是公网可访问 URL(视频接口没有上传端点, 见 _shared/docs 坑位 §5.21)。
本项目参考帧已提交进 GitHub 公开仓库, 直接用 raw 链接 —— 上传前会比像素尺寸,
避免"URL 指向另一张图"这类静默错配。

模式选择:
  keyframe  首帧 00_start + 尾帧 02_end(README 的主推法)。双锚 = 强制插值,
            尾帧 QC 不过就会在尾段裂开, 所以出片后必须逐帧核。
  reference images[] 锁外观, prompt 里用 <Picture 1> 指代。
            ⚠️ 01_clash 的服装/伞制式与首尾帧不一致(女剑客露腿长裙 vs 长袍),
            默认不喂它, 要试加 --with-clash。

用法:
  python3 make_video3s.py --mode keyframe            # 主推
  python3 make_video3s.py --mode keyframe --dry-run  # 只打印请求体
  python3 make_video3s.py --mode reference --with-clash
"""
import argparse, hashlib, json, os, subprocess, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFS = os.path.join(ROOT, "out", "review", "video3s_refs")
OUT = os.path.join(ROOT, "out", "review", "video3s")
BASE = os.environ.get("AGNES_BASE_URL", "https://apihub.agnes-ai.com")
MODEL = os.environ.get("AGNES_VIDEO_MODEL", "agnes-video-2.5-flash")
# flash 只有 720P; seconds 只收字符串 "4"~"12"(上游最小 4 秒), 出片后再 trim 到 3 秒
SECONDS = "4"
SIZE = "720P"
ASPECT = "16:9"
BRANCH = os.environ.get("MANJU_REF_BRANCH", "arena/f4ee7e05-manju")
RAW = f"https://raw.githubusercontent.com/1121427423/manju/{BRANCH}/out/review/video3s_refs"

# 参考图与提示词的唯一来源就是那个目录的 README —— 这里逐字复用, 不另写一版
PROMPT = (
    "生成一段 3 秒、16:9 的电影感连续动作镜头。严格以首帧和尾帧作为画面起止状态；"
    "中间参考图只用于约束交锋动作。固定中景广角镜头，机位稳定，不切镜、不变焦。"
    "场景始终是雨中的圆形石台与青色风暴遗迹。\n\n"
    "动作按时间推进：0–0.5 秒，两人短暂对峙蓄势；0.5–1.4 秒，白衣黑发男剑客向右前方快速踏步刺出；"
    "1.4–1.8 秒，剑尖撞上银发女剑客的圆形伞盾，接触点迸出一簇短促、局部的金青火花；"
    "1.8–2.4 秒，男剑客受力后撤半步、剑锋下沉，女剑客稳稳持盾；2.4–3.0 秒，两人停在尾帧姿势，"
    "火花熄弱，雨势持续。动作有明确的起势、加速、碰撞和回稳，人物身体与武器做连贯的真实运动，"
    "不做静帧推拉。\n\n"
    "全程保持两位角色与参考图一致：同一张脸、发型、年龄感、身形、服装颜色与结构；"
    "男角色只持一把直剑，女角色只持一面圆形伞盾。白衣袖口、衣摆长度和分片保持稳定，"
    "不凭空增加长尾或飘带。伞盾结构不变。背景石柱、圆形石台及远处建筑位置稳定；"
    "只允许人物、武器、接触火花和少量近身雨水运动。脸部清晰可辨，人体关节自然，"
    "动作流畅有重量感，电影级写实奇幻质感。"
)
NEGATIVE = (
    "face morphing, identity change, costume change, extra limbs, duplicate person, "
    "duplicate sword, duplicate shield, extra weapon, long trailing cloth, extra ribbons, "
    "melting body, warped anatomy, flickering, full-frame ripple, background bending, "
    "camera shake, zoom, cuts, giant explosion, excessive sparks, text, logo, subtitles"
)

FRAMES = {"start": "00_start.jpg", "clash": "01_clash.jpg", "end": "02_end.jpg"}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def key():
    k = os.environ.get("AGNES_TOKEN_PLAN_KEY", "").strip()
    if not k:
        # 非交互 shell 不会 source ~/.zshrc(坑位 §5.23), 这里兜底读一次
        zsh = os.path.expanduser("~/.zshrc")
        if os.path.exists(zsh):
            for line in open(zsh, encoding="utf-8", errors="replace"):
                line = line.strip()
                if line.startswith("export AGNES_TOKEN_PLAN_KEY="):
                    k = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not k:
        sys.exit("no key: AGNES_TOKEN_PLAN_KEY 未设置(环境与 ~/.zshrc 都没有)")
    return k


def api(path, body=None, timeout=150):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + key())
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:400]}
    except Exception as e:
        return 0, {"error": {"message": f"{type(e).__name__}: {e}"}}


REF_PROXY = (os.environ.get("REF_PROXY") or os.environ.get("https_proxy")
             or os.environ.get("HTTPS_PROXY")
             or ("http://127.0.0.1:10987" if os.environ.get("USE_LOCAL_PROXY", "1") == "1" else ""))


def _fetch_ref(u, timeout=45):
    """本机取参考图要过代理(直连 raw.githubusercontent 在这台机器上 SSL 握手超时);
    这一步只做"URL 指向的字节与本地一致"的比对, 失败时降级为警告 —— 上游取图不受影响。"""
    if REF_PROXY:
        op = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": REF_PROXY, "https": REF_PROXY}))
    else:
        op = urllib.request.build_opener()
    req = urllib.request.Request(u, headers={"User-Agent": "manju-video3s/1.0"})
    with op.open(req, timeout=timeout) as r:
        return r.status, r.read()


def check_public(urls, strict=False):
    """参考图 URL 必须先确认是"同一张图", 否则视频会忠实地插值一张错误的尾帧。"""
    for name, path in FRAMES.items():
        if path not in urls:
            continue
        local = os.path.join(REFS, path)
        if not os.path.exists(local):
            sys.exit(f"缺本地参考图: {local}")
        want = os.path.getsize(local)
        u = f"{RAW}/{path}"
        try:
            st, body = _fetch_ref(u)
        except Exception as e:
            msg = f"参考图 URL 本机取不到: {u} ({type(e).__name__}: {e})"
            if strict:
                sys.exit(msg)
            log("WARN " + msg + " —— 继续(上游按 URL 自行取图)")
            continue
        if st != 200 or len(body) != want:
            sys.exit(f"参考图不匹配: {u} http={st} remote={len(body)}B local={want}B")
        log(f"ref ok {path} {len(body)//1024}KB sha={hashlib.sha256(body).hexdigest()[:12]}")


def submit(payload, max_try=4):
    """建任务: 429/503 按 AGENTS §八 的退避(70s→300s), 其余 4xx 直接报错。"""
    backoff = 70
    for i in range(1, max_try + 1):
        st, d = api("/v1/videos", payload, timeout=180)
        vid = d.get("video_id") or d.get("id") or d.get("task_id") if isinstance(d, dict) else None
        if st == 200 and vid:
            return vid, d
        msg = json.dumps(d, ensure_ascii=False)
        log(f"create 失败 #{i} http={st} {msg[:200]}")
        retryable = st in (0, 429, 503, 500, 502, 504) or "video_queue_full" in msg
        if not retryable or i == max_try:
            sys.exit(f"建任务失败, 放弃: http={st} {msg[:300]}")
        log(f"{backoff}s 后重试")
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)
    sys.exit("unreachable")


def poll(vid, model, timeout=1800):
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        st, d = api(f"/agnesapi?video_id={vid}&model_name={model}", timeout=45)
        s = d.get("status") if isinstance(d, dict) else None
        if s != last:
            log(f"status={s} progress={d.get('progress') if isinstance(d, dict) else '?'} "
                f"({int(time.time()-t0)}s)")
            last = s
        if s in ("completed", "failed"):
            return s, d
        time.sleep(5)
    return "timeout", {}


def download(url, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # 直链在第三方对象存储上, 不带凭据才对(坑位: 把 provider 凭据发过去 = 凭据外用)
    req = urllib.request.Request(url, headers={"User-Agent": "manju-video3s/1.0"})
    with urllib.request.urlopen(req, timeout=600) as r:
        blob = r.read()
    if b"ftyp" not in blob[:12]:
        sys.exit(f"下载的不是 mp4: {blob[:80]!r}")
    open(dst, "wb").write(blob)
    log(f"saved {dst} {len(blob)//1024}KB")
    return dst


def ff(*args):
    return subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=False)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                        "-show_entries", "format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        return {"size": f"{s.get('width')}x{s.get('height')}", "fps": s.get("r_frame_rate"),
                "frames": s.get("nb_frames"), "duration": float((d.get("format") or {}).get("duration") or 0)}
    except Exception:
        return {}


def sheet(src, out_jpg, cols=3, rows=3, at=None):
    """拼联络表: 按时间点抽帧再用 PIL 拼(ffmpeg 无 drawtext, 不依赖滤镜字。"""
    from PIL import Image
    tmp = os.path.join("/tmp", "v3s_frames")
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    times = at or [i * 0.5 for i in range(cols * rows)]
    imgs = []
    for i, t in enumerate(times):
        p = os.path.join(tmp, f"f{i:02d}.png")
        ff("-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", p)
        if os.path.exists(p):
            imgs.append((t, Image.open(p).convert("RGB")))
    if not imgs:
        return None
    w, h = imgs[0][1].size
    cw, ch = w // 2, h // 2
    canvas = Image.new("RGB", (cw * cols, ch * rows), (12, 16, 20))
    for i, (t, im) in enumerate(imgs[:cols * rows]):
        canvas.paste(im.resize((cw, ch)), ((i % cols) * cw, (i // cols) * ch))
    canvas.save(out_jpg, quality=88)
    log(f"contact sheet -> {out_jpg}")
    return out_jpg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["keyframe", "reference"], default="keyframe")
    ap.add_argument("--with-clash", action="store_true", help="reference 模式下把 01_clash 也喂进去")
    ap.add_argument("--seconds", default=SECONDS)
    ap.add_argument("--size", default=SIZE)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--tag", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-trim", action="store_true")
    ap.add_argument("--strict-refcheck", action="store_true")
    a = ap.parse_args()

    model, seconds, size = a.model, a.seconds, a.size

    if a.mode == "keyframe":
        urls = [FRAMES["start"], FRAMES["end"]]
        payload = {"model": model, "prompt": PROMPT, "mode": "keyframe",
                   "first_frame": f"{RAW}/{FRAMES['start']}",
                   "last_frame": f"{RAW}/{FRAMES['end']}",
                   "seconds": str(seconds), "size": size, "aspect_ratio": ASPECT}
    else:
        urls = [FRAMES["start"], FRAMES["end"]] + ([FRAMES["clash"]] if a.with_clash else [])
        refs = "\n".join(f"<Picture {i+1}> 是画面{'起始状态' if i == 0 else '结束状态' if i == 1 else '中间交锋动作'}"
                         for i in range(len(urls)))
        payload = {"model": model, "prompt": refs + "\n\n" + PROMPT, "mode": "reference",
                   "images": [f"{RAW}/{u}" for u in urls],
                   "seconds": str(seconds), "size": size, "aspect_ratio": ASPECT}

    check_public(urls, strict=a.strict_refcheck)
    if a.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    log(f"提交 {model} mode={a.mode} size={size} seconds={seconds}")
    vid, created = submit(payload)
    log(f"video_id={vid}")
    status, final = poll(vid, model)
    if status != "completed":
        sys.exit(f"任务未完成: {status} {json.dumps(final, ensure_ascii=False)[:300]}")
    url = final.get("url")
    if not url:
        sys.exit(f"completed 但无 url: {json.dumps(final, ensure_ascii=False)[:300]}")

    stem = f"video3s_{model.replace('/', '_')}_{a.mode}" + (f"_{a.tag}" if a.tag else "")
    raw_mp4 = os.path.join(OUT, stem + "_raw.mp4")
    download(url, raw_mp4)

    info = {"model": model, "mode": a.mode, "video_id": vid, "url": url,
            "seconds_requested": str(seconds), "size": size, "aspect_ratio": ASPECT,
            "refs": [f"{RAW}/{u}" for u in urls], "prompt": payload["prompt"],
            "negative_prompt_text": NEGATIVE, "raw_file": raw_mp4,
            "raw_probe": probe(raw_mp4), "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    if not a.no_trim:
        trimmed = os.path.join(OUT, stem + "_3s.mp4")
        # 只裁时长不重编码: flash 出 4 秒, 分镜要 3 秒; 首 3 秒覆盖 起势→碰撞→回稳
        r = ff("-i", raw_mp4, "-t", "3", "-c", "copy", "-movflags", "+faststart", trimmed)
        if r.returncode != 0 or not os.path.exists(trimmed):
            log("stream copy 失败, 退回复编码")
            ff("-i", raw_mp4, "-t", "3", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
               "-an", "-movflags", "+faststart", trimmed)
        info["trimmed_file"] = trimmed
        info["trimmed_probe"] = probe(trimmed)
        log(f"trimmed -> {trimmed} {info['trimmed_probe']}")

    sheet(raw_mp4, os.path.join(OUT, stem + "_sheet.jpg"), cols=4, rows=3,
          at=[i * 4.0 / 11 for i in range(12)])

    json.dump(info, open(os.path.join(OUT, stem + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: info[k] for k in ("video_id", "mode", "raw_probe", "trimmed_probe")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
