"""Test the fixed TikTokHomepageExtractor."""
import asyncio
import sys
sys.path.insert(0, '.')

# We need to mock the dependencies since this is a standalone test
import types

# Create mock modules for zaizaicat dependencies
class MockLogger:
    def info(self, msg, *args): print(f"  [INFO] {msg % args if args else msg}")
    def warning(self, msg, *args): print(f"  [WARN] {msg % args if args else msg}")
    def error(self, msg, *args): print(f"  [ERR] {msg % args if args else msg}")

class MockProxy:
    async def detect_proxy(): return None

# Setup mocks
mock_logger_mod = types.ModuleType('core.utils.logger')
mock_logger_mod.get_logger = lambda: MockLogger()
sys.modules['core.utils.logger'] = mock_logger_mod
sys.modules['core.utils'] = types.ModuleType('core.utils')
sys.modules['core'] = types.ModuleType('core')
sys.modules['core.utils.logger'] = mock_logger_mod

mock_proxy_mod = types.ModuleType('core.utils.proxy')
mock_proxy_mod.detect_proxy = MockProxy.detect_proxy
sys.modules['core.utils.proxy'] = mock_proxy_mod

# Now import
import importlib.util
spec = importlib.util.spec_from_file_location(
    "tiktok_homepage", "_tiktok_homepage_v2.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

async def main():
    extractor = mod.TikTokHomepageExtractor()
    print("Testing extractor with @polestoryflix...")
    result = await extractor.extract("https://www.tiktok.com/@polestoryflix")
    
    if result:
        print(f"\n{'='*60}")
        print(f"SUCCESS! {len(result)} dramas extracted")
        print(f"{'='*60}")
        for i, d in enumerate(result[:10]):
            name = d.get('name', '?')
            plays = d.get('play_count', '0')
            eps = d.get('episode_count', 0)
            tags = ', '.join(d.get('tags', [])[:2])
            print(f"  [{i+1:2d}] {name[:45]:45s} | {eps:>3d} eps | plays={plays:>8s} | {tags}")
        if len(result) > 10:
            print(f"  ... and {len(result)-10} more")
    else:
        print("FAILED: No dramas found")

asyncio.run(main())
