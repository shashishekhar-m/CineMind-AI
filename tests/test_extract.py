from pathlib import Path

from etl import extract


def test_get_dataset_info_accepts_uncompressed_tsv(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    dataset = raw_dir / "title.basics.tsv"

    dataset.write_text(
        "tconst\ttitleType\tprimaryTitle\n"
        "tt1234567\tmovie\tTest Movie\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        extract.settings,
        "imdb_data_path",
        raw_dir,
    )

    info = extract.get_dataset_info("title_basics")

    assert info.path == dataset
    assert info.file_name == "title.basics.tsv"
    assert info.compressed is False