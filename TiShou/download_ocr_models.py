#!/usr/bin/env python3
# =============================================================================
# TiShou — EasyOCR 离线模型下载脚本
# 版本：v2.3.0
# =============================================================================
# 用途：从 EasyOCR 官方模型中心下载 3 个 PyTorch 模型到 ./models
#       craft_mlt_25k.pth  — CRAFT 文本检测 (~200MB)
#       zh_sim_g2.pth      — 简体中文识别 (~100MB)
#       english_g2.pth     — 英文识别 (~100MB)
#
# 模型来源：https://www.jaided.ai/easyocr/modelhub/
# 下载策略：GitCode 国内镜像 → GitHub Releases 官方（自动回退）
#
# 使用方法：
#     python download_ocr_models.py          # 交互式（需确认）
#     python download_ocr_models.py --yes    # 跳过确认
# =============================================================================

import os
import sys
import zipfile
import ssl
import hashlib
import shutil
import urllib.request
import urllib.error

# ─────────────────────────────────────────────────────────────
# 模型存储目录
# ─────────────────────────────────────────────────────────────
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

# ─────────────────────────────────────────────────────────────
# 模型清单
# 来源: https://www.jaided.ai/easyocr/modelhub/
# 下载优先级: GitCode 镜像 → GitHub Releases
# ─────────────────────────────────────────────────────────────

GITCODE_BASE = "https://gitcode.com/JaidedAI/EasyOCR/raw/master/model"

# GitHub Releases 官方下载地址（提取自 easyocr/config.py）
GITHUB_CRAFT  = "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip"
GITHUB_ZH_SIM = "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/zh_sim_g2.zip"
GITHUB_EN_G2  = "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip"

MODELS = [
    {
        "filename": "craft_mlt_25k.pth",
        "size_mb": 200,
        "desc": "CRAFT 文本检测模型",
        "urls": [
            f"{GITCODE_BASE}/craft_mlt_25k.pth",
            GITHUB_CRAFT,
        ],
    },
    {
        "filename": "zh_sim_g2.pth",
        "size_mb": 100,
        "desc": "简体中文识别模型",
        "urls": [
            f"{GITCODE_BASE}/zh_sim_g2.pth",
            GITHUB_ZH_SIM,
        ],
    },
    {
        "filename": "english_g2.pth",
        "size_mb": 100,
        "desc": "英文识别模型",
        "urls": [
            f"{GITCODE_BASE}/english_g2.pth",
            GITHUB_EN_G2,
        ],
    },
]


def download_file(url, dest_path, desc):
    """
    带进度条的 HTTP 下载，自动检测非模型文件
    :return: True=成功, False=失败
    """
    ssl_ctx = ssl.create_default_context()
    headers = {
        "User-Agent": "TiShou-OCR-Downloader/2.3.0",
        "Accept": "application/octet-stream",
    }
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=120) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type:
                print(f"\n  [跳过] 服务器返回 HTML（非模型文件）")
                return False

            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 65536

            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded * 100 / total)
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total / (1024 * 1024)
                        bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
                        print(
                            f"\r  [{bar}] {pct:3d}%  {mb_done:.1f}/{mb_total:.1f} MB",
                            end="",
                        )

            actual_size = os.path.getsize(dest_path)
            if actual_size < 1024 * 1024:
                print(f"\n  [失败] 文件过小 ({actual_size} bytes)")
                os.remove(dest_path)
                return False

            with open(dest_path, "rb") as check_f:
                header = check_f.read(2)
            if header != b"PK":
                print(f"\n  [失败] 非 PyTorch 模型格式")
                os.remove(dest_path)
                return False

            print(f"\r  [{'#' * 20}] 100%  下载完成{' ' * 15}")
            return True

    except urllib.error.HTTPError as e:
        print(f"\n  [失败] HTTP {e.code}")
        return False
    except urllib.error.URLError as e:
        print(f"\n  [失败] 网络错误: {e.reason}")
        return False
    except Exception as e:
        print(f"\n  [失败] {e}")
        return False


def extract_zip(zip_path, extract_dir):
    """解压 zip 并提取 .pth"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            pth_files = [n for n in names if n.endswith(".pth")]
            if not pth_files:
                print(f"    警告: zip 中无 .pth: {names}")
                return False
            for pth_file in pth_files:
                zf.extract(pth_file, extract_dir)
                print(f"    解压: {pth_file}")
            return True
    except zipfile.BadZipFile:
        return False
    except Exception as e:
        print(f"    解压失败: {e}")
        return False


def verify_model(pth_path):
    """
    校验模型文件完整性
    :return: (size_mb, md5_hex)
    """
    if not os.path.exists(pth_path):
        return 0, "缺失"
    size_mb = os.path.getsize(pth_path) / (1024 * 1024)
    h = hashlib.md5()
    with open(pth_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return size_mb, h.hexdigest()


def main():
    skip_confirm = "--yes" in sys.argv or "-y" in sys.argv

    print("=" * 55)
    print("  TiShou EasyOCR 离线模型下载工具 v2.3.0")
    print("=" * 55)
    print()
    print("模型来源: https://www.jaided.ai/easyocr/modelhub/")
    print()

    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"目标目录: {MODELS_DIR}")
    print()

    total_size = sum(m["size_mb"] for m in MODELS)
    print(f"准备下载 {len(MODELS)} 个模型（总计约 {total_size}MB）")
    print("下载策略: 1) GitCode 镜像  2) GitHub Releases 官方")
    print()

    print("清单:")
    for m in MODELS:
        print(f"  • {m['filename']}  (~{m['size_mb']}MB) — {m['desc']}")
    print()

    if not skip_confirm:
        resp = input("确认下载？(y/n): ").strip().lower()
        if resp not in ("y", "yes", "是"):
            print("已取消。")
            sys.exit(0)
    print()

    # ── 下载 ──
    all_ok = True
    for model in MODELS:
        filename = model["filename"]
        pth_path = os.path.join(MODELS_DIR, filename)

        if os.path.exists(pth_path):
            size_mb, md5 = verify_model(pth_path)
            if size_mb > 5:
                print(f"  [{filename}] 已存在 ({size_mb:.1f} MB) → 跳过\n")
                continue
            else:
                print(f"  [{filename}] 异常 ({size_mb:.1f} MB)，重新下载")
                os.remove(pth_path)

        print(f"  [{filename}] {model['desc']} (~{model['size_mb']}MB)")

        downloaded = False
        for url in model["urls"]:
            source = "GitCode" if "gitcode" in url else "GitHub"
            is_zip = url.endswith(".zip")
            dest = os.path.join(MODELS_DIR, filename + ".zip" if is_zip else filename)

            print(f"    [{source}] {url[:90]}...")
            if download_file(url, dest, model["desc"]):
                downloaded = True
                if is_zip and zipfile.is_zipfile(dest):
                    print("    解压中...")
                    if extract_zip(dest, MODELS_DIR):
                        os.remove(dest)
                    else:
                        shutil.move(dest, pth_path)
                elif is_zip:
                    shutil.move(dest, pth_path)
                break
            else:
                if os.path.exists(dest):
                    os.remove(dest)
                print(f"    [{source}] 失败，切换备用源...")

        if not downloaded:
            print(f"  [{filename}] 所有源均失败！")
            all_ok = False
        print()

    # ── 校验 ──
    print("=" * 55)
    print("  模型校验")
    print("=" * 55)
    print()
    print("-" * 55)
    all_valid = True
    for model in MODELS:
        fn = model["filename"]
        pp = os.path.join(MODELS_DIR, fn)
        size_mb, md5 = verify_model(pp)
        ok = "✓" if size_mb > 5 else "✗"
        print(f"  [{ok}] {fn:25s} {size_mb:7.1f} MB  MD5: {md5[:16]}...")
        if size_mb < 5:
            all_valid = False
    print("-" * 55)
    print(f"\n文件位置: {MODELS_DIR}")

    if all_valid:
        print()
        print("=" * 55)
        print("  校验通过！")
        print("=" * 55)
        print()
        print("后续步骤:")
        print("  1. 本地验证:  python main.py")
        print("     → 观察日志: 'easyocr ch_sim 模型加载成功'")
        print("  2. APK 打包:  .\\docker_build_apk.ps1")
        print("     → 模型通过 buildozer.spec 自动打包进 APK")
        print()
        print("说明:")
        print("  • 模型已加入 .gitignore，不提交 Git")
        print("  • 模型中心: https://www.jaided.ai/easyocr/modelhub/")
    else:
        print()
        print("校验未通过，重试:")
        print("  python download_ocr_models.py --yes")
        sys.exit(1)


if __name__ == "__main__":
    main()