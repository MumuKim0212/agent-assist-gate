from core import attributes


def test_longest_surface_wins():
    assert attributes.extract("저희는 비회원사입니다") == {"대상": "비회원사"}
    assert attributes.extract("저희는 회원사입니다") == {"대상": "회원사"}


def test_two_values_of_one_attribute_means_not_stated():
    assert "등급" not in attributes.extract("지금 초급인데 중급 가려면 어떻게 해요")


def test_bare_승급_is_not_a_grade_change():
    assert "행위" not in attributes.extract("승급교육은 몇 시간이에요")
    assert attributes.extract("중급으로 승급하려고요")["행위"] == "변경"


def test_absence_is_not_a_mismatch():
    doc = {"attributes": {"등급": "초급"}}
    assert not attributes.mismatch({}, doc)
    assert not attributes.mismatch({"등급": "초급"}, doc)
    assert attributes.mismatch({"등급": "중급"}, doc)
    assert not attributes.mismatch({"등급": "중급"}, {"attributes": {}})


def test_competing_attributes_differ():
    a, b = {"attributes": {"대상": "회원사"}}, {"attributes": {"대상": "비회원사"}}
    assert attributes.competing_attributes_differ([a, b])
    assert not attributes.competing_attributes_differ([a, a])
    # an untagged document is "not applicable", not a different value
    assert not attributes.competing_attributes_differ([a, {"attributes": {}}])
