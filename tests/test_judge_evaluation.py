from scripts.evaluate_judge import summarize


def test_metrics_abstention_and_confusion():
    def row(label, prediction, status="ok"):
        return dict(label=label, prediction=prediction, status=status,
                    schema_valid=status == "ok", risk_score=.5,
                    trace=dict(latency_ms=10, total_tokens=None))
    report = summarize([
        row("unauthorized", "unauthorized"), row("authorized", "unauthorized"),
        row("unauthorized", "authorized"), row("authorized", "authorized"),
        row("unauthorized", "uncertain", "timeout"),
    ])
    assert report["tp"] == report["fp"] == report["fn"] == report["tn"] == 1
    assert report["precision"] == report["recall"] == report["f1"] == .5
    assert report["coverage"] == report["structured_output_success_rate"] == .8
    assert report["abstentions_by_label"] == {"unauthorized": 1}
    assert report["risk_histogram"]["counts"] == [0, 0, 4, 0, 0]
    assert report["token_usage_available_calls"] == 0


def test_empty_metrics_are_not_fabricated():
    report = summarize([])
    assert report["f1"] is None and report["coverage"] is None
