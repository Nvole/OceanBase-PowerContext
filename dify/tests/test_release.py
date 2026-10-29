import importlib.util
import json
from pathlib import Path

import pytest
import yaml


PROJECT = Path(__file__).resolve().parents[1]


def load_checker():
    spec = importlib.util.spec_from_file_location("submission_checker", PROJECT / "scripts/verify_submission.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_checkout_cannot_pass(tmp_path):
    with pytest.raises(ValueError, match="Missing required tracked files"):
        load_checker().audit_checkout(tmp_path)


def test_runtime_is_not_a_substitute_for_evidence():
    checker = (PROJECT / "scripts/verify_submission.py").read_text(encoding="utf-8")
    assert '"backend_restart_preserves_seekdb_memory"' in checker
    assert '"anonymous_remote_clone": False' in checker
    assert '"checkout", "--detach"' in checker
    assert '"credential.helper="' in checker


def test_dify_cannot_reach_backend_via_container_loopback():
    document = yaml.safe_load((PROJECT / "docs/absurd_debate.dsl.yml").read_text(encoding="utf-8"))
    assert document["workflow"]["environment_variables"][0]["value"] == "http://debate:18604"
    assert document["dependencies"] == []
    assert any(node["data"]["type"] == "code" for node in document["workflow"]["graph"]["nodes"])


def test_pinned_real_dify_runtime_and_persistent_storage():
    compose = yaml.safe_load((PROJECT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["services"]["api"]["image"] == "langgenius/dify-api:1.12.0"
    assert compose["services"]["sandbox"]["image"] == "langgenius/dify-sandbox:0.2.12"
    assert compose["services"]["api"]["ports"]
    assert compose["volumes"]
