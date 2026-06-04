import pytest
from vcam_bridge.config import load_config
from vcam_bridge.domain.errors import ConfigError
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


def test_load_rejects_bad_M_shape(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("calibration:\n  M_ue2dis: [[1,0,0],[0,1,0],[0,0,1]]\n")
    with pytest.raises(ConfigError):
        load_config(str(p))


def test_load_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/path/config.yaml")


def test_load_bad_yaml_syntax(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("chunk_size: [invalid\n  yaml: {broken")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(str(p))


def test_load_invalid_schema_field(tmp_path):
    p = tmp_path / "bad_schema.yaml"
    p.write_text("chunk_size: not_a_number\n")
    with pytest.raises(ConfigError, match="invalid config schema"):
        load_config(str(p))


def test_load_m_ue2dis_valid_4x4(tmp_path):
    p = tmp_path / "ok.yaml"
    p.write_text("calibration:\n  M_ue2dis:\n    - [1,0,0,0]\n    - [0,1,0,0]\n    - [0,0,1,0]\n    - [0,0,0,1]\n")
    cfg = load_config(str(p))
    assert len(cfg.calibration.M_ue2dis) == 4
    assert all(len(row) == 4 for row in cfg.calibration.M_ue2dis)
