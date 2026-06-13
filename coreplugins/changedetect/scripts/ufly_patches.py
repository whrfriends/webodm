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


# --- Patch 4: forward LLM API key from host to container -----------------
# The changedetect plugin's AI features (ai.py) read the LLM key from
# the container environment. We copy it from the host's
# ~/.hermes/.env on every container start so the user doesn't have
# to do anything special after a rebuild.
def patch_forward_llm_key(_target):
    """Best-effort forward of MINIMAX_CN_API_KEY + MINIMAX_CN_BASE_URL
    from the host's Hermes .env into the webapp container's env.
    """
    import subprocess
    # Read from a path the host has bind-mounted or that ufly's
    # wrapper wrote before our patch ran. We try a few locations.
    candidates = [
        '/var/lib/ufly/host.env',         # ufly-style host env bridge
        '/host-root/.hermes/.env',        # bind-mount of host home
        os.path.expanduser('~/.hermes/.env'),  # in-container home (rare)
    ]
    parsed = {}
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    v = v.strip().strip('"').strip("'")
                    parsed[k.strip()] = v
        except Exception as e:
            log.debug(f"could not read {path}: {e}")
    if not parsed.get('MINIMAX_CN_API_KEY'):
        # Try: maybe the host passed it through docker-compose env:
        # `docker inspect webapp` would show it, but we can't run that
        # from inside. Fall back to asking the orchestrator via a
        # well-known path. We also accept it being set in our own
        # process env (ufly wraps the container with the host's env).
        for k in ('MINIMAX_CN_API_KEY', 'MINIMAX_CN_BASE_URL'):
            v = os.environ.get(k)
            if v:
                parsed[k] = v
    if not parsed:
        log.info("LLM API key: not found in any candidate path; AI endpoints will return a clear error")
        return None
    # Write to /tmp/ufly-llm.env which start.sh sources before starting
    # gunicorn. Idempotent: overwrite every start so the user can edit
    # the host .env and a container restart picks up the new key.
    target = '/tmp/ufly-llm.env'
    try:
        with open(target, 'w') as f:
            for k, v in parsed.items():
                if k.startswith('MINIMAX_CN_'):
                    f.write(f'{k}="{v}"\n')
        log.info(f"LLM API key: wrote {len(parsed)} vars to {target}")
    except Exception as e:
        log.warning(f"failed to write {target}: {e}")
    return None


register('/tmp/__ufly_llm_marker__',
         'LLM API key forward failed',  # never present → runs every start
         patch_forward_llm_key)


# --- Patch 5: register the changedetect plugin in INSTALLED_APPS -------
# The ufly 嵌入版 image's webodm/settings.py ships without the
# changedetect plugin in INSTALLED_APPS, so Django's migration
# machinery (manage.py migrate, makemigrations, etc) doesn't see our
# models. WebODM's plugin loader registers the plugin at *runtime*,
# but that happens after `apps.populate()` has already run, so DB
# migrations are skipped. We patch the in-container settings.py
# to add our AppConfig — idempotent, re-applied on every container
# start.
def patch_settings_installed_apps(target):
    with open(target, 'r', encoding='utf-8') as f:
        src = f.read()
    if 'coreplugins.changedetect.apps.ChangeDetectConfig' in src:
        return None  # already patched
    # Insert the entry just after the line containing 'nodeodm','
    # which is the last plugin in the list. We use a regex so we
    # tolerate the exact trailing whitespace.
    import re
    m = re.search(r"^(\s*'nodeodm',\s*)$", src, re.MULTILINE)
    if not m:
        log.warning("could not find 'nodeodm' entry in INSTALLED_APPS; "
                    "skipping changedetect patch")
        return None
    new = src[:m.end()] + "\n    'coreplugins.changedetect.apps.ChangeDetectConfig'," + src[m.end():]
    return new


register('/webodm/webodm/settings.py',
         'coreplugins.changedetect.apps.ChangeDetectConfig',
         patch_settings_installed_apps)


# --- Patch 6: source /tmp/ufly-llm.env in start.sh before gunicorn ------
# Patch 4 writes the LLM key file but start.sh never sources it, so the
# gunicorn master process ends up with no MINIMAX_CN_API_KEY in its
# environment — every LLM call then fails with the "key not set" error.
# Fix: inject a single `source` line right above the gunicorn call.
def patch_start_sh_source_llm_env(target):
    with open(target, 'r', encoding='utf-8') as f:
        src = f.read()
    if 'source /tmp/ufly-llm.env' in src:
        return None  # already injected
    # The marker we look for is the start of the gunicorn command line.
    marker = 'gunicorn webodm.wsgi --bind'
    if marker not in src:
        log.warning("patch_start_sh_source_llm_env: gunicorn marker not found, skipping")
        return None
    injection = '\n# changedetect: load LLM API key for the gunicorn process\n    if [ -f /tmp/ufly-llm.env ]; then\n        set -a; source /tmp/ufly-llm.env; set +a\n    fi\n    '
    return src.replace(marker, injection + marker)


register('/webodm/start.sh',
         'source /tmp/ufly-llm.env',
         patch_start_sh_source_llm_env)


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
