"""Tester för den läckagefria motståndarmodellen.

Det viktigaste testet är att modellen aldrig kan lära sig något ur framtiden:
tärningarna får bara komma in via :meth:`OpponentTracker.reveal`, och bara efter
att en syn redan avgjorts. Detta var ett verkligt problem — ``session.py`` loggar
de faktiska tärningarna för varje påstående, och bygger man profilen ur hela loggen
"vet" agenten att ett påstående var en bluff fast ingen kunde veta det än.
"""

from meier.opponents import OpponentTracker


def test_unseen_bids_are_not_promises():
    tracker = OpponentTracker()
    tracker.observe_bid("a", unseen=True)
    # Ett påstående utan att titta är inget löfte: ingen profil skapas alls för det.
    assert "a" not in tracker.stats
    tracker.observe_bid("a", unseen=False)
    assert tracker.stats["a"].visible_bids == 1


def test_bluff_estimate_defaults_to_global_before_any_reveal():
    tracker = OpponentTracker()
    tracker.observe_bid("a", unseen=False)
    assert tracker.bluff_estimate("a") == tracker.global_q


def test_bluff_estimate_uses_only_revealed_bids():
    tracker = OpponentTracker()
    # Fyra synliga påståenden, men bara ett avslöjat — och det var en bluff.
    for _ in range(4):
        tracker.observe_bid("a", unseen=False)
    tracker.reveal("a", was_bluff=True)
    # Ett avslöjat påstående som var en bluff höjer tron över förhandstron:
    # (1 + 4*DEFAULT_Q) / (1 + 4) > DEFAULT_Q för alla DEFAULT_Q > 0.
    assert tracker.bluff_estimate("a") > tracker.global_q
    assert tracker.stats["a"].revealed == 1


def test_reveal_of_truth_lowers_estimate():
    tracker = OpponentTracker()
    tracker.reveal("a", was_bluff=False)
    assert tracker.bluff_estimate("a") < tracker.global_q


def test_bluff_ratio_is_one_without_data():
    tracker = OpponentTracker()
    assert tracker.bluff_ratio("okand") == 1.0


def test_bluff_ratio_tracks_a_serial_bluffer():
    tracker = OpponentTracker()
    for _ in range(10):
        tracker.reveal("a", was_bluff=True)
    assert tracker.bluff_ratio("a") > 1.0


def test_effective_prior_keeps_the_bid_profile_at_reading_zero():
    from meier.policy import CALL_PRIOR

    tracker = OpponentTracker()
    for _ in range(10):
        tracker.reveal("a", was_bluff=True)
    # reading = 0 ska ge exakt den frysta tabellen, oavsett motståndare.
    for bid in CALL_PRIOR:
        assert tracker.effective_prior(bid, "a", reading=0.0) == CALL_PRIOR[bid]


def test_effective_prior_scales_relative_not_absolute():
    from meier.policy import CALL_PRIOR

    tracker = OpponentTracker()
    for _ in range(10):
        tracker.reveal("a", was_bluff=True)
    # Lågt påstående: den absoluta bluff-frekvensen är hög, men tron ska fortfarande
    # vara låg — annars synar agenten påståenden som nästan alltid är sanna.
    low = tracker.effective_prior(41, "a", reading=1.0)
    assert low < 0.5


def test_give_up_rate_counts_passes():
    tracker = OpponentTracker()
    tracker.observe_decision("a", "skicka")
    tracker.observe_decision("a", "skicka")
    tracker.observe_decision("a", "syna")
    assert tracker.give_up_rate("a") == 2 / 3


def test_give_up_rate_is_none_without_decisions():
    tracker = OpponentTracker()
    assert tracker.give_up_rate("okand") is None


def test_call_outcome_is_attributed_to_the_caller():
    tracker = OpponentTracker()
    tracker.record_call_outcome("a", won=True)
    tracker.record_call_outcome("a", won=False)
    assert tracker.stats["a"].calls_won == 1
