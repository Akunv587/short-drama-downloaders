"""Verify all zaizaicat imports."""
import sys
sys.path.insert(0, r"<WORKSPACE>\zaizaicat")

errors = []

# Core imports
modules = [
    ('core.utils.file_utils', ['run_subprocess', 'safe_file_replace', 'ensure_dir']),
    ('core.utils.logger', ['get_logger']),
    ('core.utils.cookie', ['auto_extract_cookies', 'COOKIES_FILE']),
    ('core.utils.proxy', ['detect_proxy']),
    ('core.platform.base', ['BasePlatformAdapter', 'EpisodeInfo', 'ProgressInfo', 'PlatformMeta']),
    ('core.download_engine', ['DownloadResult', 'EpisodeInfo']),
    ('core.platform.detector', ['detect_platform']),
    ('core.platform.dramashorts', ['DramaShortsAdapter']),
    ('core.platform.shortmax', ['ShortMaxAdapter']),
    ('core.platform.tiktok', ['TikTokAdapter']),
    ('core.platform.hls_engine', ['download_hls']),
    ('core.extractors.dramashorts_episodes', []),
    ('core.extractors.shortmax_episodes', []),
    ('core.extractors.tiktok_series', []),
    ('core.extractors.tiktok_homepage', []),
    ('core.audio.loudnorm', ['LoudnormProcessor']),
    ('core.audio.mixer', ['AudioMixer']),
    ('core.database.connection', ['get_db']),
    ('core.database.settings_repo', ['get_all_settings', 'set_setting']),
    ('core.scheduler', []),
    ('core.task_manager', []),
]

for mod_name, attrs in modules:
    try:
        mod = __import__(mod_name, fromlist=[''])
        for attr in attrs:
            if not hasattr(mod, attr):
                errors.append(f'{mod_name}: missing attr {attr}')
        print(f'  OK: {mod_name}')
    except Exception as e:
        errors.append(f'{mod_name}: {e}')
        print(f'  FAIL: {mod_name} - {e}')

# API routes
api_modules = [
    'api.routes.download',
    'api.routes.extract',
    'api.routes.audio',
    'api.routes.drama',
    'api.routes.text',
    'api.routes.settings',
    'api.routes.logs',
    'api.routes.platform',
    'api.routes.history',
    'api.websocket_manager',
]

for mod_name in api_modules:
    try:
        __import__(mod_name)
        print(f'  OK: {mod_name}')
    except Exception as e:
        errors.append(f'{mod_name}: {e}')
        print(f'  FAIL: {mod_name} - {e}')

print()
if errors:
    print(f'ERRORS ({len(errors)}):')
    for e in errors:
        print(f'  - {e}')
else:
    print('ALL IMPORTS PASSED!')
