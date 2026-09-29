#!/usr/bin/env python3
"""Safely add bounded upload and same-app PDF preview rules to the current site."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


CONFIG = Path("/etc/nginx/sites-available/certificate-manager")
CSP_LINE = re.compile(r'^(\s*add_header\s+Content-Security-Policy\s+")(.*?)("\s+always;\s*)$', re.MULTILINE)
API_LOCATION = re.compile(r"^(\s*)location\s+/api/\s*\{\s*(?:#.*)?$", re.MULTILINE)


def update_config(original: str) -> tuple[str, int, int]:
    lines = original.splitlines(keepends=True)
    upload_locations = 0
    csp_headers = 0
    index = 0
    while index < len(lines):
        match = API_LOCATION.match(lines[index].rstrip("\r\n"))
        if not match:
            index += 1
            continue
        start = index
        depth = 1
        cursor = index + 1
        block: list[str] = []
        while cursor < len(lines) and depth:
            content = lines[cursor].split("#", 1)[0]
            depth += content.count("{") - content.count("}")
            block.append(content)
            cursor += 1
        if depth:
            raise ValueError("站点配置中的 /api/ 块没有闭合")
        if not any(re.search(r"\bclient_max_body_size\b", line) for line in block):
            indent = match.group(1) + "    "
            newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
            lines.insert(start + 1, f"{indent}client_max_body_size 16m;{newline}")
            cursor += 1
        upload_locations += 1
        index = cursor

    if not upload_locations:
        raise ValueError("当前站点中找不到 /api/ 代理位置，未修改 Nginx")
    updated = "".join(lines)

    def update_csp(match: re.Match[str]) -> str:
        nonlocal csp_headers
        policy = match.group(2)
        if "frame-src 'self' blob:" not in policy:
            if "form-action 'self'" in policy:
                policy = policy.replace("form-action 'self'", "frame-src 'self' blob:; form-action 'self'")
            else:
                policy += "; frame-src 'self' blob:"
        csp_headers += 1
        return f"{match.group(1)}{policy}{match.group(3)}"

    updated = CSP_LINE.sub(update_csp, updated)
    if not csp_headers:
        raise ValueError("当前站点中找不到安全响应头配置，未修改 Nginx")
    return updated, upload_locations, csp_headers


def atomic_write(data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".certificate-manager-nginx-", dir=CONFIG.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, CONFIG.stat().st_mode & 0o777)
        os.replace(temporary, CONFIG)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    if os.geteuid() != 0:
        print("请使用 sudo 运行此脚本。", file=sys.stderr)
        return 1
    if CONFIG.is_symlink() or not CONFIG.is_file():
        print(f"Nginx 站点文件不存在或是符号链接：{CONFIG}", file=sys.stderr)
        return 1
    original = CONFIG.read_bytes()
    try:
        updated, locations, headers = update_config(original.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        print(f"{error}; 原配置未修改。", file=sys.stderr)
        return 1
    if updated.encode("utf-8") == original:
        print("Nginx 上传大小限制和安全预览策略已经配置。")
        return 0

    backup = CONFIG.with_name(f"certificate-manager.before-attachments-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.conf")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(backup, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_write(updated.encode("utf-8"))
    validated = subprocess.run(["nginx", "-t"], check=False)
    reloaded = subprocess.run(["systemctl", "reload", "nginx"], check=False) if validated.returncode == 0 else None
    if validated.returncode != 0 or reloaded is None or reloaded.returncode != 0:
        atomic_write(original)
        subprocess.run(["nginx", "-t"], check=False)
        print(f"Nginx 更新失败，已恢复原配置；备份保留在 {backup}", file=sys.stderr)
        return 1
    print(f"Nginx 已更新：{locations} 个 API 位置启用 16 MB 请求上限，{headers} 条 CSP 增加了 PDF 预览许可。")
    print(f"原站点配置备份：{backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
