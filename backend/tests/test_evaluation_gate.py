import copy
import json

from scripts.check_evaluation_gate import check_report, main


def sample():
    baseline = {"dataset_id": "synthetic-regression-v1", "split": "dev",
                "corpus_sha256": "a" * 64, "split_sha256": "b" * 64,
                "expected_questions": 1, "chunk_size": 1024, "chunk_overlap": 64,
                "minimum_recall_at_5": {"vector": .98, "bm25": .98, "hybrid": .98}}
    report = {"status": "complete", "strategy": "vector_only", "split": "dev",
              "dataset_id": "synthetic-regression-v1", "corpus_sha256": "a" * 64,
              "split_sha256": "b" * 64, "expected_questions": 1,
              "results": [{"generation": None}],
              "config": {"chunk_size": 1024, "chunk_overlap": 64},
              "summary": {"recall_at_5": 1.0}}
    return baseline, report


def test_gate_accepts_matching_complete_retrieval_run():
    baseline, report = sample()
    assert check_report(report, baseline, "vector")["passed"]


def test_gate_rejects_regression_incomplete_run_and_wrong_fixture():
    baseline, report = sample()
    report["summary"]["recall_at_5"] = .9
    report["results"] = []
    report["corpus_sha256"] = "wrong"
    result = check_report(report, baseline, "vector")
    assert not result["passed"] and len(result["failures"]) == 3


def test_gate_rejects_generation_and_nonfinite_metric():
    baseline, report = sample()
    report["results"][0]["generation"] = {"status": "answered"}
    report["summary"]["recall_at_5"] = float("nan")
    assert not check_report(report, baseline, "vector")["passed"]


def test_cli_requires_all_three_reports(tmp_path, monkeypatch, capsys):
    baseline, report = sample()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    report_path = tmp_path / "vector.json"
    report_path.write_text(json.dumps(copy.deepcopy(report)), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["gate", "--baseline", str(baseline_path),
                                  "--reports", str(tmp_path)])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        assert False, "missing BM25 and hybrid reports must fail"
    assert "Missing report" in capsys.readouterr().out
