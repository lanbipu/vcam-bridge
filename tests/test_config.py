from vcam_bridge.config import load_config
from vcam_bridge.domain.models import Config


def test_load_default_when_none():
    cfg = load_config(None)
    assert isinstance(cfg, Config)
    assert cfg.chunk_size == 200
    assert cfg.calibration.euler_order == "XYZ"


def test_load_from_yaml(tmp_path):
    p = tmp_path / "vcam.yaml"
    p.write_text("chunk_size: 50\ndirector: 'host:80'\ncalibration:\n  euler_order: ZYX\n")
    cfg = load_config(str(p))
    assert cfg.chunk_size == 50
    assert cfg.director == "host:80"
    assert cfg.calibration.euler_order == "ZYX"
