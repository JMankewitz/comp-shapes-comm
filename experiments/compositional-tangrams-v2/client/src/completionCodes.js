// Prolific completion codes, in one place.
//
// Three distinct codes so submissions can be told apart in the Prolific list.
// Define ALL THREE in Prolific with the **approve** action, NOT "screened out":
// Prolific throttles recruitment against the number of screen-out slots you
// advertise, so using a screen-out code caps how fast the study fills. Approving
// everyone and paying for time spent avoids that entirely, and the 1.74
// recruited-per-kept ratio in the design doc (S6.1) already budgets for it.
//
// What each group is owed differs even though all are approved:
//   COMPLETE   full base + the $0.03/correct bonus from the training phase
//   INCOMPLETE base (or prorated) -- they worked, their partner or the
//              connection failed. Not their fault; do not return these.
//   NO_MATCH   prorated for lobby time. They never entered a game.
//
// COMPLETE and INCOMPLETE deliberately share one code (set 2026-08): Prolific is
// configured with a single default completion path for both. They remain
// distinguishable in the DATA -- `completedStudy` is true only for participants
// who finished the post-test, and `finishedTraining` only for those whose game
// reached the end of training -- so bonus decisions can still be made per group.
export const COMPLETION_CODES = {
  // Finished the post-test and the exit survey.
  COMPLETE: "C1NK2P4O",

  // Reached a game, but it ended before training finished (inactivity timeout,
  // or a partner who dropped).
  INCOMPLETE: "C1NK2P4O",

  // Never matched into a game at all (lobby timeout, no partner available).
  //
  // NO LONGER SHOWN TO PARTICIPANTS (changed 2026-08). Unmatched participants are
  // asked to RETURN the submission instead, and are paid by bulk bonus afterwards.
  // Prolific confirms a returned or timed-out submission is still bonusable, and
  // returning frees the recruitment place so another participant can be matched --
  // whereas submitting a code consumes a place that produced no data. This also
  // avoids custom-screening slots entirely, which throttle recruitment whenever
  // slots < places and leave an unspent reservation to reclaim.
  //
  // Kept defined so the Prolific study config and this file stay in sync.
  NO_MATCH: "CG2CK987",
};
