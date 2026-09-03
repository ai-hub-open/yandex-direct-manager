"""upload_creatives_to_storage: сбор картинок, заливка в KeepImage, манифест.

Сеть замокана: conftest запрещает реальный connect, здесь подменяем requests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

import scripts.upload_creatives_to_storage as up


# ---------- фейковый HTTP ----------

class FakeResp:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _fake_put_factory(record):
    def _put(url, data=None, headers=None, timeout=None):
        record.append({"url": url, "headers": headers})
        name = url.rsplit("/", 1)[-1]
        return FakeResp(200, {
            "id": "ID" + name,
            "url": f"https://storage.aihub.click.ru/f/ID{name}/{name}",
            "content_type": "image/png",
            "size": 1234,
            "expires_at": "2026-09-03T16:00:00.000Z",
        })
    return _put


def _write_png_paths(ws: Path, rels: list[str]):
    for rel in rels:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)


# ---------- collect_images ----------

def test_collect_from_creatives(tmp_path):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["assets/img/a.png", "assets/img/b.png"])
    (ws / "08_creatives.json").write_text(json.dumps({
        "groups": [
            {"combined_ad": {"images": ["assets/img/a.png", "assets/img/b.png"]}},
            {"combined_ad": {"images": ["assets/img/a.png"]}},  # дубль
        ]
    }), encoding="utf-8")
    imgs = up.collect_images(ws, all_assets=False, explicit=None)
    names = sorted(p.name for p in imgs)
    assert names == ["a.png", "b.png"]  # дубль схлопнут


def test_collect_all_assets(tmp_path):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["assets/images/x.png", "assets/images/y.jpg"])
    (ws / "assets" / "images" / "notes.txt").write_text("skip me", encoding="utf-8")
    imgs = up.collect_images(ws, all_assets=True, explicit=None)
    names = sorted(p.name for p in imgs)
    assert names == ["x.png", "y.jpg"]  # txt отфильтрован


def test_collect_explicit_files(tmp_path):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["a.png"])
    imgs = up.collect_images(ws, all_assets=False, explicit=["a.png"])
    assert [p.name for p in imgs] == ["a.png"]


def test_collect_creatives_missing_file(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert up.collect_images(ws, all_assets=False, explicit=None) == []


# ---------- upload_one ----------

def test_upload_one_success(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["a.png"])
    rec = []
    monkeypatch.setattr(up.requests, "put", _fake_put_factory(rec))
    r = up.upload_one(ws / "a.png", token="TKN", ttl=7200)
    assert r["status"] == "ok"
    assert r["url"].endswith("/a.png")
    assert rec[0]["headers"]["X-Auth-Token"] == "TKN"
    assert rec[0]["headers"]["X-Ttl-Seconds"] == "7200"


def test_upload_one_missing_file_no_network(tmp_path):
    # файла нет — ошибка без обращения к сети (conftest бы упал на реальном connect)
    r = up.upload_one(tmp_path / "nope.png", token="TKN", ttl=7200)
    assert r["status"] == "fail"
    assert "не найден" in r["error"]


def test_upload_one_bad_suffix(tmp_path):
    p = tmp_path / "bad.bmp"
    p.write_bytes(b"x")
    r = up.upload_one(p, token="TKN", ttl=7200)
    assert r["status"] == "fail"
    assert "не поддерживается" in r["error"]


def test_upload_one_http_error(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["a.png"])
    monkeypatch.setattr(up.requests, "put", lambda *a, **k: FakeResp(413, None, "too large"))
    r = up.upload_one(ws / "a.png", token="TKN", ttl=7200)
    assert r["status"] == "fail"
    assert "413" in r["error"]


def test_upload_one_master_account_user_id_header(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["a.png"])
    rec = []
    monkeypatch.setattr(up.requests, "put", _fake_put_factory(rec))
    monkeypatch.setattr(up, "_user_id", lambda: "1696784")
    up.upload_one(ws / "a.png", token="TKN", ttl=7200)
    assert rec[0]["headers"]["X-Auth-UserId"] == "1696784"


# ---------- main ----------

def test_main_writes_manifest_and_ok(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["assets/img/a.png", "assets/img/b.png"])
    (ws / "08_creatives.json").write_text(json.dumps({
        "groups": [{"combined_ad": {"images": ["assets/img/a.png", "assets/img/b.png"]}}]
    }), encoding="utf-8")
    monkeypatch.setenv("CLICK_RU_TOKEN", "TKN")
    monkeypatch.setattr(up.requests, "put", _fake_put_factory([]))

    code = up.main(["--workspace", str(ws)])
    assert code == 0
    manifest = json.loads((ws / "assets" / "storage_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 2
    assert all(r["status"] == "ok" and r["url"] for r in manifest)


def test_main_reports_failure_exit_1(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["assets/img/a.png"])
    (ws / "08_creatives.json").write_text(json.dumps({
        "groups": [{"combined_ad": {"images": ["assets/img/a.png", "assets/img/missing.png"]}}]
    }), encoding="utf-8")
    monkeypatch.setenv("CLICK_RU_TOKEN", "TKN")
    monkeypatch.setattr(up.requests, "put", _fake_put_factory([]))

    code = up.main(["--workspace", str(ws)])
    assert code == 1
    manifest = json.loads((ws / "assets" / "storage_manifest.json").read_text(encoding="utf-8"))
    statuses = {Path(r["local"]).name: r["status"] for r in manifest}
    assert statuses["a.png"] == "ok"
    assert statuses["missing.png"] == "fail"


def test_main_dry_run_no_network_no_manifest(tmp_path):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["assets/img/a.png"])
    (ws / "08_creatives.json").write_text(json.dumps({
        "groups": [{"combined_ad": {"images": ["assets/img/a.png"]}}]
    }), encoding="utf-8")
    # без мока сети: если бы полез в сеть — conftest уронил бы тест
    code = up.main(["--workspace", str(ws), "--dry-run"])
    assert code == 0
    assert not (ws / "assets" / "storage_manifest.json").exists()


def test_main_no_images_ok(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    code = up.main(["--workspace", str(ws)])
    assert code == 0


def test_main_missing_token_exit_1(tmp_path):
    ws = tmp_path / "ws"
    _write_png_paths(ws, ["assets/img/a.png"])
    (ws / "08_creatives.json").write_text(json.dumps({
        "groups": [{"combined_ad": {"images": ["assets/img/a.png"]}}]
    }), encoding="utf-8")
    # токена нет ни в env (conftest чистит), ни в реестре (HOME изолирован) — до сети не доходим
    code = up.main(["--workspace", str(ws)])
    assert code == 1


def test_main_requires_workspace_or_files():
    assert up.main([]) == 2
