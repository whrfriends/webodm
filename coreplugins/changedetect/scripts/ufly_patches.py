"""
ufly 嵌入版 patches — auto-applied by start.sh at webapp container startup.

This file is loaded by /webodm/start.sh (a wrapper around the WebODM
entrypoint) and patches the WebODM source tree in place *before* gunicorn
starts, so Django imports see the patched code.  Because
coreplugins/changedetect/ is bind-mounted into the container, edits on
the host take effect on the next container restart without rebuilding
the image.

Why: the upstream WebODM CSRF check is incompatible with ufly's
embedded-mode plugin POST flow — every plugin POST gets 403'd because
the URL-resolved callback (app_view_handler / api_view_handler) has no
csrf_exempt flag, even though the dispatched mount_point view does.
We patch the top-level handlers in app/plugins/views.py to wrap them
with csrf_exempt.  See coreplugins/changedetect/README.md for the
full analysis.

Usage from start.sh (injected at the very top of gunicorn startup):

    if [ -f /webodm/coreplugins/changedetect/scripts/ufly_patches.py ]; then
        /webodm/venv/bin/python /webodm/coreplugins/changedetect/scripts/ufly_patches.py || true
    fi
"""
import os
import sys
import hashlib
import logging

logging.basicConfig(level=logging.INFO,
                    format='ufly-patches %(levelname)s: %(message)s')
log = logging.getLogger('ufly-patches')

# Each entry is (target_path, marker_string, new_content_callback).
# new_content_callback(target_path) reads the existing file and returns
# the patched text, or None to skip if already patched (idempotent).
# The marker is a substring we look for in the file to decide whether
# the patch is already applied — this way the script is safe to run on
# every container start.
PATCHES = []


def register(target_rel, marker, patch_fn):
    PATCHES.append((target_rel, marker, patch_fn))


# --- Patch 1: csrf_exempt wrap on app_view_handler / api_view_handler --
def patch_views_py(target):
    with open(target, 'r', encoding='utf-8') as f:
        src = f.read()
    if 'app_view_handler = csrf_exempt(app_view_handler)' in src:
        return None  # already patched
    # Insert import at the top
    if 'from django.views.decorators.csrf import csrf_exempt' not in src:
        import re
        m = re.search(r'^(from django\.http[^\n]*\n)', src, re.MULTILINE)
        if m:
            src = src[:m.end()] + 'from django.views.decorators.csrf import csrf_exempt\n' + src[m.end():]
        else:
            src = 'from django.views.decorators.csrf import csrf_exempt\n' + src
    # Strip any prior half-applied text (clean state from old drafts)
    import re
    src = re.sub(r'\n"""ufly 嵌入版修改[^\n]*\n(?:[^\n]*\n)*?"""\n', '\n', src)
    src = re.sub(r'\n# ufly 嵌入版修改[^\n]*\n(?:[^\n]*\n)*?\n', '\n', src)
    src = re.sub(r'\nfrom django\.views\.decorators\.csrf import csrf_exempt\n+', '\n', src)
    if 'from django.views.decorators.csrf import csrf_exempt' not in src:
        m = re.search(r'^(from django\.http[^\n]*\n)', src, re.MULTILINE)
        if m:
            src = src[:m.end()] + 'from django.views.decorators.csrf import csrf_exempt\n' + src[m.end():]
    wrap_block = '''

# ufly 嵌入版 patch: csrf_exempt on top-level plugin handlers.
# WebODM 顶层 CsrfViewMiddleware 检查的是 URL 解析返回的 callback
# (即 app_view_handler / api_view_handler)，不检查 handler 内部调用的
# view。Plugin 的 view 通过 mount_points 间接调用，所以即使 view 本身
# csrf_exempt=True，POST 也会被 403。ufly 嵌入版用 session + csrftoken
# 已认证，plugin 内部用自己的权限校验。
app_view_handler = csrf_exempt(app_view_handler)
api_view_handler = csrf_exempt(api_view_handler)
'''
    if wrap_block.strip() not in src:
        src = src.rstrip() + '\n' + wrap_block
    return src


register('/webodm/app/plugins/views.py',
         'app_view_handler = csrf_exempt(app_view_handler)',
         patch_views_py)


# --- Patch 2: gunicorn capture output so worker stderr shows in logs ---
def patch_start_sh(target):
    with open(target, 'r', encoding='utf-8') as f:
        src = f.read()
    if '--capture-output --log-level debug' in src:
        return None
    old = 'gunicorn webodm.wsgi --bind unix:/tmp/gunicorn.sock --timeout 300000 --max-requests 5000 --workers $WEB_CONCURRENCY --preload'
    new = 'gunicorn webodm.wsgi --bind unix:/tmp/gunicorn.sock --timeout 300000 --max-requests 5000 --workers $WEB_CONCURRENCY --preload --capture-output --log-level debug --log-file -'
    if old in src:
        src = src.replace(old, new)
    return src


register('/webodm/start.sh',
         '--capture-output --log-level debug',
         patch_start_sh)


# --- Patch 3: install CJK fonts (needed for PDF reports with Chinese) -
def patch_install_cjk_fonts(_target):
    """Best-effort install of fonts-wqy-microhei. We don't have access to
    the apt index inside a generic patch, so we just check whether the
    font is already on disk and if not, try a single `apt-get install`.

    Marker is a comment we put into the file system; we mark success by
    writing /tmp/ufly-cjk-fonts-installed once. If the install fails we
    log a warning and continue — the report will still work, but
    Chinese characters will render as '?'.
    """
    import subprocess
    marker = '/tmp/ufly-cjk-fonts-installed'
    if os.path.exists(marker):
        return None
    if os.path.exists('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'):
        # Already installed
        with open(marker, 'w') as f:
            f.write('ok\n')
        return None
    log.info('installing fonts-wqy-microhei (one-time)')
    try:
        subprocess.run(
            ['apt-get', 'install', '-y', 'fonts-wqy-microhei'],
            check=True, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'},
            capture_output=True, timeout=120,
        )
        with open(marker, 'w') as f:
            f.write('ok\n')
        log.info('CJK fonts installed')
    except Exception as e:
        log.warning(f"CJK font install failed: {e}; Chinese chars may be '?'")
    # No file is patched by this entry — it's a side-effect patch.
    return None


# We use a synthetic target so the runner hits our function. The marker
# is the side-effect file we just write.
register('/tmp/__ufly_cjk_marker__',
         'CJK font install failed',  # never present → runs every start (idempotent via /tmp marker)
         patch_install_cjk_fonts)


# --- Runner ------------------------------------------------------------
def main():
    base = '/webodm'
    if not os.path.isdir(base):
        log.warning(f"{base} not a directory — running outside container?")
        return 0
    applied = 0
    for rel, marker, fn in PATCHES:
        target = os.path.join(base, rel.lstrip('/')) if not rel.startswith('/') else rel
        if not os.path.exists(target):
            log.warning(f"target {target} does not exist, skipping")
            continue
        with open(target, 'r', encoding='utf-8') as f:
            cur = f.read()
        if marker in cur:
            log.info(f"already patched: {target}")
            continue
        new = fn(target)
        if new is None:
            continue
        if new == cur:
            log.info(f"no change: {target}")
            continue
        backup = target + '.ufly-bak'
        if not os.path.exists(backup):
            with open(backup, 'w', encoding='utf-8') as f:
                f.write(cur)
            log.info(f"backup written: {backup}")
        with open(target, 'w', encoding='utf-8') as f:
            f.write(new)
        log.info(f"patched: {target} ({len(cur)} -> {len(new)} bytes, hash "
                 f"{hashlib.sha1(new.encode()).hexdigest()[:10]})")
        applied += 1
    log.info(f"applied {applied} patch(es)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
