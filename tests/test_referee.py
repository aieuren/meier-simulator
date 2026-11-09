"""Tester för domaragenten."""

from mejeri.agents.referee import RefereeAgent, Verdict


class SilentLLM:
    """LLM som aldrig anropas (use_llm=False) eller ger tomt svar."""

    def complete(self, system, user, *, json_mode=False):
        return '{"ok": true, "comment": ""}'


def rule_only_referee() -> RefereeAgent:
    return RefereeAgent(llm=SilentLLM(), use_llm=False)


def test_approves_valid_bid():
    ref = rule_only_referee()
    verdict = ref.review_announcement((2, 5), 52)
    assert isinstance(verdict, Verdict)
    assert verdict.ok is True
    assert verdict.objections == []


def test_rejects_invalid_outcome():
    ref = rule_only_referee()
    verdict = ref.review_announcement((2, 5), 99)
    assert verdict.ok is False
    assert any("giltigt" in o for o in verdict.objections)


def test_rejects_raise_that_is_not_higher():
    ref = rule_only_referee()
    # Spelaren slår efter 65 men säger 52 (lägre) -> invändning.
    verdict = ref.review_announcement((2, 5), 52, previous_bid=65)
    assert verdict.ok is False
    assert any("höjer inte" in o for o in verdict.objections)


def test_approves_raise_that_is_higher():
    ref = rule_only_referee()
    verdict = ref.review_announcement((2, 5), 63, previous_bid=62)
    assert verdict.ok is True


def test_mejer_is_higher_than_66():
    ref = rule_only_referee()
    verdict = ref.review_announcement((2, 1), 21, previous_bid=66)
    assert verdict.ok is True


def test_judges_the_models_raw_proposal():
    # Modellen föreslog ett ogiltigt utfall (99) som korrigerades till 52.
    ref = rule_only_referee()
    verdict = ref.review_announcement((2, 5), 52, proposed=99, corrected=True)
    assert verdict.ok is False
    assert any("giltigt" in o for o in verdict.objections)


def test_judges_proposal_that_is_not_higher():
    # Modellen föreslog 52 efter ett bud på 65; det är ett regelbrott.
    ref = rule_only_referee()
    verdict = ref.review_announcement((2, 5), 65, previous_bid=65, proposed=52, corrected=True)
    assert verdict.ok is False
    assert any("höjer inte" in o for o in verdict.objections)


def test_review_decision_valid_raise():
    ref = rule_only_referee()
    verdict = ref.review_decision("slå", bid=52, new_bid=65)
    assert verdict.ok is True


def test_review_decision_invalid_raise():
    ref = rule_only_referee()
    verdict = ref.review_decision("slå", bid=65, new_bid=52)
    assert verdict.ok is False
    assert any("höjer inte" in o for o in verdict.objections)


def test_review_decision_raise_without_bid():
    ref = rule_only_referee()
    verdict = ref.review_decision("slå", bid=52, new_bid=None)
    assert verdict.ok is False


def test_review_decision_unknown_action():
    ref = rule_only_referee()
    verdict = ref.review_decision("hoppa", bid=52)
    assert verdict.ok is False


def test_llm_cannot_override_formal_error():
    class OverrideLLM:
        def complete(self, system, user, *, json_mode=False):
            return '{"ok": true, "comment": "Ser bra ut!"}'

    ref = RefereeAgent(llm=OverrideLLM(), use_llm=True)
    # Formellt fel: 52 är inte högre än 65.
    verdict = ref.review_announcement((2, 5), 52, previous_bid=65)
    assert verdict.ok is False


def test_llm_comment_is_used_when_valid():
    class CommentLLM:
        def complete(self, system, user, *, json_mode=False):
            return '{"ok": true, "comment": "Korrekt bud, inget att anmärka."}'

    ref = RefereeAgent(llm=CommentLLM(), use_llm=True)
    verdict = ref.review_announcement((2, 5), 52)
    assert verdict.ok is True
    assert verdict.source == "llm"
    assert "Korrekt" in verdict.comment
