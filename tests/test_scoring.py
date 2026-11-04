from app.domain.scoring import CheckResult, build_report, cap_grade, grade_for, layer_score


def r(cid, layer, sev, status, **kw):
    return CheckResult(check_id=cid, layer=layer, severity=sev, method="D", status=status, **kw)


W = {"discovery": 50, "data": 50, "protocol": 0}


def test_layer_score_uses_severity_weights_and_excludes_na_and_skipped():
    rs = [r("a", "discovery", "CRITICAL", "pass"), r("b", "discovery", "MAJOR", "fail"),
          r("c", "discovery", "HIGH", "na"), r("d", "discovery", "HIGH", "skipped"), r("e", "discovery", "INFO", "fail")]
    assert layer_score(rs) == 4 / 6 * 100
    assert layer_score([r("x", "data", "HIGH", "na")]) is None


def test_warn_counts_half():
    assert layer_score([r("a", "data", "HIGH", "warn")]) == 50


def test_readiness_renormalises_layers_without_applicable_checks():
    rs = [r("a", "discovery", "HIGH", "pass"), r("b", "data", "HIGH", "na")]
    rep = build_report("dealer", W, rs)
    assert rep.readiness == 100.0  # data layer has no applicable checks, so only discovery counts
    assert [l.score for l in rep.layers] == [100.0, None, None]


def test_weights_are_applied_between_layers():
    rs = [r("a", "discovery", "HIGH", "pass"), r("b", "data", "HIGH", "fail")]
    assert build_report("dealer", {"discovery": 25, "data": 75}, rs).readiness == 25.0


def test_grade_boundaries():
    assert [grade_for(x) for x in (100, 90, 89.9, 75, 74.9, 60, 59.9, 40, 39.9, 0)] == list("AABBCCDDFF")
    assert grade_for(90) == "A" and grade_for(75) == "B" and grade_for(60) == "C" and grade_for(40) == "D" and grade_for(39.9) == "F"


def test_cap_grade():
    assert cap_grade("A") == "C" and cap_grade("B") == "C" and cap_grade("C") == "C" and cap_grade("D") == "D"


def test_critical_fail_caps_grade_but_not_the_score():
    rs = [r("ok", "discovery", "HIGH", "pass"), r("ok2", "data", "HIGH", "pass"), r("ok3", "data", "HIGH", "pass"),
          r("ok4", "data", "HIGH", "pass"), r("ok5", "data", "HIGH", "pass"), r("bad", "data", "MINOR", "fail")]
    rs[-1] = r("bad", "data", "CRITICAL", "fail")
    rep = build_report("dealer", {"discovery": 90, "data": 10}, rs)
    assert rep.grade_before_gate == "A" or rep.grade_before_gate == "B"
    assert rep.gate_applied and rep.gate_checks == ["bad"] and rep.grade == "C"
    assert rep.grade_before_gate == grade_for(rep.ax_score)


def test_not_adopted_critical_fail_does_not_trigger_gate():
    rs = [r("ok", "discovery", "HIGH", "pass"), r("aap", "protocol", "CRITICAL", "fail", not_adopted=True)]
    rep = build_report("dealer", {"discovery": 90, "protocol": 10}, rs)
    assert not rep.gate_applied and rep.grade == grade_for(rep.ax_score)


def test_info_severity_is_reported_but_not_scored():
    rep = build_report("dealer", {"discovery": 100}, [r("a", "discovery", "HIGH", "pass"), r("i", "discovery", "INFO", "fail")])
    assert rep.readiness == 100.0 and rep.coverage["scored"] == 1 and rep.coverage["total"] == 2


def test_visibility_blends_into_ax_score():
    rep = build_report("dealer", {"discovery": 100}, [r("a", "discovery", "HIGH", "pass")], visibility=50)
    assert rep.ax_score == 80.0


def test_skipped_checks_flag_partial_coverage():
    rep = build_report("dealer", {"discovery": 100}, [r("a", "discovery", "HIGH", "pass"), r("j", "discovery", "HIGH", "skipped")])
    assert rep.coverage["partial"] and rep.coverage["skipped"] == ["j"]
