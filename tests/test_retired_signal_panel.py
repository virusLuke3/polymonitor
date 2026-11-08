import pytest
from api.runtime_panels.registry import get_panel_by_id, get_panel_by_route, get_default_panel_ids
from runtime.signals_watcher import COMPONENTS, build_arg_parser


def test_retired_panel_has_no_registry_or_worker_entry():
    for panel_id in ('polysignal-feed', 'polybeats-feed'):
        assert get_panel_by_id(panel_id) is None
        assert panel_id not in get_default_panel_ids()
    for route in ('/runtime/signals/polysignal', '/runtime/signals/polybeats'):
        assert get_panel_by_route(route) is None
    assert set(COMPONENTS) == {'alpha', 'whales', 'suspicious'}
    for component in ('polysignal', 'polybeats'):
        with pytest.raises(SystemExit):
            build_arg_parser().parse_args(['--component', component])
