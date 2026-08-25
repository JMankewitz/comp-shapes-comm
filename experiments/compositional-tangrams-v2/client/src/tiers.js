// ONE definition of which compensation tier a participant is in.
//
// This existed in three places at once -- App.jsx (which exit page to show),
// Finished.jsx (which code and instructions to print), and the payment logic in
// analysis/exp2/00_preprocessing.R -- and they disagreed. Finished.jsx handed a
// completion code to lobby-timeout participants while the exit page told them to
// return, and promised $2.50 to people owed $1.00. A participant who is told two
// different things messages you, and is right to.
//
// Keep this in sync with 00_preprocessing.R, which is authoritative for what is
// actually paid. These constants are the MESSAGING; that file is the money.
export const PAY = {
  BASE: 11.0, // full study, paid by approving the Prolific submission
  LOBBY: 2.5, // held a slot but produced nothing
  NO_LOBBY: 1.0, // some intro, turned away before ever reaching a lobby
  NO_INTRO: 0, // turned away at entry, saw nothing
};

export const money = (n) => `$${n.toFixed(2)}`;

const gaveText = (arr) =>
  Array.isArray(arr) && arr.some((r) => String(r?.text || "").trim() !== "");

// Did they do ANYTHING? Deliberately conservative: chat messages and selections
// are round-scoped and unreadable from the exit steps, so this only sees
// descriptions, training completion, and score. 00_preprocessing.R checks the
// other channels too and can promote someone back to full pay -- never demote --
// so the error direction is overpaying someone who tried.
export function contributed(player) {
  return (
    gaveText(player.get("pretestResponses")) ||
    gaveText(player.get("posttestResponses")) ||
    Boolean(player.get("finishedTraining")) ||
    Number(player.get("score") || 0) > 0
  );
}

export function hasGame(player) {
  const g = player.get("gameID");
  return Boolean(g) && g !== "null";
}

// The tier for a participant who did NOT complete the study. Callers handle the
// completed case themselves, because "completed" means different things at
// different moments (finishedTraining before the post-test, completedStudy after).
export function exitTier(player) {
  const ended = String(player.get("ended") || "");
  // Empirica writes this only from expiredIndividualLobbyTimeout(), which
  // returns early unless `game.hasStarted` is false -- so it provably implies
  // zero data. Must be tested BEFORE hasGame(): these players do have a game.
  if (ended.startsWith("lobby timed out")) return "lobby";
  if (!hasGame(player)) {
    // `intro` is written only once a player enters the intro flow, so its
    // absence means they were turned away at entry and saw nothing.
    return player.get("intro") !== undefined ? "no_lobby" : "no_intro";
  }
  // In a game that ran, but contributed nothing: they occupied a slot and cost
  // their partner the session.
  if (!contributed(player)) return "lobby";
  return "incomplete";
}

// Tiers that must NOT receive a completion code. Approving a Prolific
// submission pays the full study reward, so handing a code to someone owed the
// flat lobby amount either overpays them or forces a rejection.
export const NO_CODE_TIERS = ["lobby", "no_lobby", "no_intro"];
