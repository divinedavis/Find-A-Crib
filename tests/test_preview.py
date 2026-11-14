"""scripts/preview.py: which requests the checkout answers and which go live."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('preview', ROOT / 'scripts' / 'preview.py')
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
L = P.LIVE


def rel(url, **kw):
    f = P.local_file(url, **kw)
    return f.relative_to(ROOT).as_posix() if f else None



def test_pages_and_assets_come_from_the_checkout():
    assert rel(L + '/') == 'web/index.html'
    assert rel(L + '/?q=bronx') == 'web/index.html'
    assert rel(L + '/sf/') == 'web/sf/index.html'
    assert rel(L + '/static/supercluster/supercluster.min.js') == 'web/static/supercluster/supercluster.min.js'


def test_config_and_service_worker_always_come_from_live():
    assert rel(L + '/config.js?v=6') is None
    assert rel(L + '/sw.js') is None


def test_data_files_are_live_unless_asked():
    assert rel(L + '/fmr.json') is None
    assert rel(L + '/fmr.json', local_data=True) == 'data/fmr.json'


def test_missing_files_other_hosts_and_escapes_go_live():
    assert rel(L + '/no-such-page/') is None
    assert rel('https://example.com/index.html') is None
    assert rel(L + '/../../etc/passwd') is None
    assert rel(L + '/%2e%2e/%2e%2e/etc/passwd') is None
