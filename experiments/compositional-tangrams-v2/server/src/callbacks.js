import _ from "lodash";
import { ClassicListenersCollector } from "@empirica/core/admin/classic";
export const Empirica = new ClassicListenersCollector();
import { promises as fs } from 'fs';
import { join } from 'path';
import {
  loadSchedule,
  loadSet,
  assignSet,
  withinTrialDisplays,
  acrossTrialDisplays,
  nonCompDisplay,
  makeDisplayPicker,
  imageURL,
  rotationForSet,
  spacedShuffle,
  withURLs,
  addDescribeRound,
  releaseSet,
} from './exp2.js';

// onGameStart/onGameEnded receive only `{ game }` -- no event context -- but the
// cross-batch set tally lives in Empirica's global scope, which is reachable
// only through a ctx. Capture one at boot and hold it for the process.
let empiricaCtx = null;
Empirica.on("start", (ctx) => {
  empiricaCtx = ctx;
  console.log("Exp 2: Empirica context captured; global set tally available");
  setInterval(() => guardAbandonedDescribeStages(ctx), DESCRIBE_WATCHDOG_TICK_MS);
});

// ---------------------------------------------------------------------------
// Pre-test abandonment guard
//
// The description stage advances only when BOTH players submit. Nothing in the
// round lifecycle fires while a phase is stalled, so a participant whose partner
// walks away has no protection except the stage duration cap -- 20+ minutes of
// staring at "Waiting for your partner". In the first pilot wave two people sat
// there for 30 and 45 minutes and returned the study.
//
// An absent participant produces no events, so this has to be polled.
//
// The check is unambiguous because of the per-item autosubmit: an ACTIVE
// participant writes a response at least once every describeSecondsPerItem
// (60s), even if they type nothing. So three minutes with zero new responses,
// while their partner has already submitted, means they are gone -- not slow.
// ---------------------------------------------------------------------------

const DESCRIBE_WATCHDOG_TICK_MS = 30 * 1000;
const DESCRIBE_ABANDON_MS = 3 * 60 * 1000;

// gameID -> { counts: "a,b", since: timestamp }
const describeProgress = new Map();

function guardAbandonedDescribeStages(ctx) {
  let games;
  try {
    games = ctx.scopesByKind("game");
  } catch (err) {
    return; // context not ready; try again next tick
  }
  if (!games) return;

  for (const [, game] of games) {
    try {
      const stage = game.currentStage;
      if (!stage || stage.get("name") !== "describe") {
        describeProgress.delete(game.id);
        continue;
      }
      if (game.hasEnded) continue;

      const round = stage.round;
      const phase = round && round.get("phase");
      if (phase !== "pretest") continue; // post-test is a solo exit step

      const players = game.players || [];
      if (players.length < 2) continue;

      const counts = players
        .map((p) => (p.get("pretestResponses") || []).length)
        .join(",");
      const anySubmitted = players.some(
        (p) => p.stage && p.stage.get("submit")
      );

      const prior = describeProgress.get(game.id);
      if (!prior || prior.counts !== counts) {
        describeProgress.set(game.id, { counts, since: Date.now() });
        continue;
      }

      const stalledFor = Date.now() - prior.since;
      if (!anySubmitted || stalledFor < DESCRIBE_ABANDON_MS) continue;

      // One partner is done, the other has written nothing for three minutes.
      // The dyad cannot proceed to training, so end the game rather than leave
      // the present participant waiting out the stage cap. They keep their
      // pre-test data and route to the incomplete exit survey.
      const stranded = players
        .filter((p) => p.stage && p.stage.get("submit"))
        .map((p) => p.id);
      console.log(
        `Game ${game.id}: pre-test abandoned -- responses stuck at [${counts}] ` +
        `for ${Math.round(stalledFor / 1000)}s with a partner already submitted. ` +
        `Ending game; stranded player(s): ${stranded.join(", ")}`
      );
      game.set("endedInactive", true);
      game.set("endedReason", "pretest abandoned by a partner");
      game.end("ended", "pretestAbandoned");
      describeProgress.delete(game.id);
    } catch (err) {
      console.error(`describe watchdog error on game ${game && game.id}:`, err);
    }
  }
}

const names = [
"Repi",
"Minu",
"Laju",
"Hera",
]; // for the players names to match avatar color

// Blue avatar names and color codes:
const avatarURLs = [
  "/avatars/blue.png",
  "/avatars/red.png",
  "/avatars/yellow.png",
  "/avatars/green.png",
]

const nameColors = [
"#29828D", // Aria
  "#444EA1", // Katherine
  "#57AEC6", // Kayla
  "#5792C8" // Oliver
]

// Get the directory name of the current module

Empirica.onGameStart(async ({ game }) => {
  // Set treatment variables for client-side access
  const treatment = game.get("treatment");
  game.set("showNegativeFeedback", treatment.showNegativeFeedback);
  game.set("contextSize", treatment.contextSize);
  game.set("contextStructure", treatment.contextStructure)
  game.set("maxTimeout", treatment.maxTimeout)
  game.set("numRoundsInactive", 0);
  game.set("endedInactive", false);
  // Exp 2: the training set, the diagonal holdout and the pre/post item lists are
  // all precomputed in exp2_{comp,noncomp}_sets.json. Read them; do not rebuild
  // the matrix here.
  const condition = game.get("contextStructure");
  let selectedSet, assignment, schedule;
  try {
    schedule = await loadSchedule();

    // assignSet claims a slot in the cross-batch global tally and writes it back
    // in the same tick, so a concurrently starting game cannot read a stale count
    // and land on the same set.
    assignment = assignSet(game, schedule, empiricaCtx?.globals);
    game.set("setId", assignment.setId);
    game.set("setIndex", assignment.setIndex);
    game.set("setReplicate", assignment.replicate);
    game.set("setSlotInReplicate", assignment.slotInReplicate);

    selectedSet = await loadSet(condition, assignment.setId);
  } catch (error) {
    console.error("Error loading Exp 2 stimulus sets:", error);
    throw error;
  }

  // Rotation follows the stimulus set, not the game, so every dyad on a given
  // set sees an identical display (S4.8). Must come after set assignment.
  const gameRotation = rotationForSet(assignment.setId);
  game.set("rotation", gameRotation);

  game.set("stimulusSchemaVersion", "exp2-1");
  // noncomp sets carry comp_set_id; it equals set_id for all 500, so all three
  // conditions post-test on identical images. Recorded explicitly so the
  // analysis never has to assume it.
  game.set("compSetId", selectedSet.comp_set_id ?? selectedSet.set_id);
  game.set("components", selectedSet.components);

  console.log(
    `Game ${game.id} (${condition}) -> set ${assignment.setId}, ` +
    `replicate ${assignment.replicate}, slot ${assignment.slotInReplicate}, ` +
    `rotation ${gameRotation}deg. ` +
    `Tally now ${JSON.stringify(assignment.tallyAfterClaim)}`
  );

  if (assignment.wrapped) {
    console.log(
      `Game ${game.id}: every scheduled set already has ` +
      `${schedule.dyads_per_condition_per_set} ${condition} dyads; wrapping onto ` +
      `set ${assignment.setId} as replicate ${assignment.replicate} ` +
      `(${assignment.priorDyadsOnSet} prior dyads on this set)`
    );
  }

  // The 12 trained shapes: {label, top, bottom, image}. For comp this is the 4x4
  // crossing minus the diagonal; for noncomp it is 4 diagonal wholes + 8 fillers.
  const targets = selectedSet.training_shapes;
  game.set("targets", targets);
  game.set("trainingLabels", targets.map((s) => s.label));

  // Pre/post free-description items (S4.3-4.5). Comp sets carry 20 at each
  // phase; NONCOMP CARRIES ONLY 8 AT PRE-TEST, deliberately (S4.6) -- the phase
  // is driven off array length, never a literal 20.
  const pretestItems = withURLs(selectedSet.pretest_items);
  const posttestItems = withURLs(selectedSet.posttest_items);
  // Read by the client for the per-item countdown; mirrored onto players below
  // because the post-test runs as an exit step where game scope is unreliable.
  game.set("describeSecondsPerItem", treatment.describeSecondsPerItem ?? 60);
  game.set("numPretestItems", pretestItems.length);
  game.set("numPosttestItems", posttestItems.length);

  // initialize players
  game.players.forEach((player, i) => {
    const otherPlayer = game.players.filter((p) => p.id != player.id);
    //player.set("tangramURLs", _.shuffle(game.get('context')));
    player.set("avatar",`https://api.dicebear.com/8.x/rings/svg?seed=${names[i]}`); //chat
    player.set("src", avatarURLs[i]);
    player.set('name', names[i]);
    player.set("nameColor", nameColors[i]);
    player.set("partner", otherPlayer[0].id)
    player.set("role", i == 0 ? 'director' : 'matcher'); //first player is always speaker (if overfill there may be multiple listeners??)
    player.set("bonus", 0);
    player.set("score", 0);
    // Each partner walks their own order so the two are not in lockstep and
    // sequence effects do not align within a dyad. Per-item measures join on
    // `image`, so partner alignment (DV5) is unaffected.
    //
    // Spaced, not plain, shuffle: consecutive items must not share a top or a
    // bottom, or the test itself demonstrates that shapes decompose (S4.5).
    // Applied to BOTH phases so pre and post are ordered by the same procedure.
    const pre = spacedShuffle(pretestItems);
    const post = spacedShuffle(posttestItems);
    player.set("pretestItems", pre.order);
    player.set("pretestItemGap", pre.gap);
    // Read by the post-test exit step, where the game scope is not reliable.
    player.set("posttestItems", post.order);
    player.set("posttestItemGap", post.gap);
    player.set("rotation", gameRotation);
    player.set("describeSecondsPerItem", treatment.describeSecondsPerItem ?? 60);
    player.set("pretestResponses", []);
    player.set("posttestResponses", []);
  });

  const reps = treatment.numRepetitionsWithPartner;
  const numTargets = targets.length; // 12 under Exp 2, was 16
  const displaySize = game.get("contextSize");

  // use this to play the sound on the UI when the game starts
  game.set("justStarted", true);

  // Enumerate every legal display once per target, then draw one per block. The
  // old code sampled competitors fresh each trial, which could land on a
  // held-out diagonal cell now that the diagonal is gone.
  const pickerFor = new Map();
  for (const target of targets) {
    if (condition === "noncomp") continue; // sampled per trial, see below
    const legal = condition === "comp-within"
      ? withinTrialDisplays(target, targets)
      : acrossTrialDisplays(target, targets);
    if (legal.length < 1) {
      throw new Error(
        `Game ${game.id}: no legal ${condition} display for target ${target.label} ` +
        `in set ${assignment.setId}`
      );
    }
    pickerFor.set(target.image, makeDisplayPicker(legal));
  }

  // ---- Pre-test: one round, one stage, iterated client-side ----------------
  // Both partners describe every item independently and ASYNCHRONOUSLY (S4.5).
  // Deliberately NOT 20 lockstep rounds: that would make each item wait on the
  // slower partner and roughly double the phase. Empirica advances the stage
  // when both players have set stage `submit`, so phase cost is max(A, B).
  addDescribeRound(game, "pretest", pretestItems.length, treatment);

  _.times(reps, repNum => {
    const block = _.shuffle(targets)

    _.times(numTargets, targetNum => {
      const target = block[targetNum]

      const display = condition === "noncomp"
        ? nonCompDisplay(target, targets, displaySize)
        : pickerFor.get(target.image)();

      const tangrams = _.shuffle(display);
      const tangramURLs = tangrams.map(imageURL);
      const targetURL = imageURL(target);

      const round = game.addRound({
        phase: "training",
        // Initialised here, at game creation, NOT only in onRoundStart. If the
        // attribute does not exist yet the client reads `undefined`, and the
        // strict `=== ""` tests in Tangram.jsx silently swallow matcher clicks
        // and hide the director's target border. See design doc S6.7.
        selection: "",
        target: targetURL,
        numTrials: reps * numTargets,
        targetNum: targetNum + 1,
        trialNum : repNum * numTargets + targetNum,
        repNum : repNum,
        reps: reps,
        numTrialsPerBlock: numTargets,
        tangramURLs: tangramURLs,
        // Analysis annotations. Labels are per-file conventions and mean
        // different things in comp vs noncomp -- see the header of exp2.js.
        targetLabel: target.label,
        displayLabels: tangrams.map((s) => s.label),
        setId: assignment.setId,
      });

      round.addStage({
        name: "selection",
        duration: treatment.selectionDuration
      });
      round.addStage({
        name: "feedback",
        duration: treatment.feedbackDuration
      });
    });
  });

  // NO post-test round. The post-test runs as an EXIT STEP
  // (client/src/intro-exit/Posttest.jsx) so a participant who finishes first
  // leaves immediately instead of waiting on their partner. Its items are on the
  // player scope already, so nothing else is needed here.

  console.log(
    `${condition} ${game.id} started -- set ${assignment.setId} ` +
    `(replicate ${assignment.replicate}), ${reps * numTargets} training trials`
  );
});

Empirica.onRoundStart(({ round }) => {

  const players = round.currentGame.players;
  round.set('selection', '')
  round.set("justStarted", true);

  // The test phases have no roles to alternate -- both partners describe every
  // item. Swapping here would still balance out, but it would write a
  // meaningless director/matcher onto the pre/post rounds.
  if (round.get("phase") !== "training") return;

  players.forEach((player, i) => {
    //player.set('clicked', '');
    // swap player roles
    player.set("role", player.get('role') == 'director' ? 'matcher' : 'director');
    round.set(player.get('role'), player.id);
  });
});

// ITEM 7 / S6.6: per-message timestamps.
//
// Empirica's built-in <Chat> exposes no send hook and the messages it stores
// carry no time field, so Exp 1 had only `chatLastChangedAt` -- the time of the
// LAST write, usable only on the 87% of rounds with a single message. This
// records one timestamp per message, making the compose/decide split available
// on multi-message rounds too.
//
// CAVEAT: this is server-RECEIVE time, not client-send time, so it includes the
// client->server leg. To size that leg, compare the client-stamped
// `selectionMadeAt` against Empirica's own server-side `selectionLastChangedAt`
// on the same round; the difference is the one-way lag.
Empirica.on("round", "chat", (_ctx, { round }) => {
  const messages = round.get("chat") || [];
  const stamps = round.get("chatTimestamps") || [];
  if (messages.length <= stamps.length) return;
  const now = Date.now();
  round.set("chatTimestamps", [
    ...stamps,
    ...Array(messages.length - stamps.length).fill(now),
  ]);
});

Empirica.onStageStart(({ stage }) => {
  // Client-side render time is stamped by Task.jsx; this is the server's view of
  // when the stage opened, and the gap between them is transition cost.
  stage.set("serverStartedAt", Date.now());
});

Empirica.onStageEnded(({ stage }) => {});

Empirica.onRoundEnded(({ round }) => {
  const players = round.currentGame.players;
  const game = round.currentGame;

  // ITEM 6: only the 48 training trials are bonusable. Free-description trials
  // have no correct answer, so no bonus can accrue -- and they must not feed the
  // inactivity counter either, or a slow describer would end the game.
  if (round.get("phase") !== "training") {
    const phase = round.get("phase");
    players.forEach((player) => {
      const responses = player.get(`${phase}Responses`) || [];
      console.log(
        `Game ${game.id} - ${phase} complete for ${player.id}: ` +
        `${responses.length}/${round.get("numItems")} items described`
      );
    });
    return;
  }

  // Counts rounds that actually finished, so completion is measured rather than
  // inferred from how the game ended. `endedInactive` only covers the inactivity
  // timeout; a partner closing their tab ends the game with that flag still
  // false, which would otherwise mark a 3-of-48 dropout as a full completion.
  game.set("trainingRoundsCompleted", (game.get("trainingRoundsCompleted") || 0) + 1);

  const target = round.get('target');
  const selectedAnswer = round.get('selection')

  // Update player scores
  players.forEach(player => {
    const currScore = player.get("bonus") || 0;
    const scoreIncrement = selectedAnswer === target ? .03 : 0;
    player.set("bonus", scoreIncrement + currScore);
    player.set("score", scoreIncrement + currScore);
  })
  const currentSelection = round.get('selection');
  const currentInactive = game.get("numRoundsInactive");

  // Inactivity is tracked PER PLAYER, not per game.
  //
  // Two failure modes have to be told apart, and neither a game-level counter nor
  // a selection-only test can do it:
  //
  //   * Both present, talking, failing to converge. Keying on `selection` alone
  //     killed exactly this: a comp-within dyad chatted every round and had their
  //     game ended at trial 19 of 48. The within-trial display always contains a
  //     top-sharer and a bottom-sharer (S4.2), so timing out is an expected
  //     outcome of the manipulation, not evidence of absence.
  //   * One player gone, the other still typing. A game-level "was there any
  //     chat" test never fires here, so the present partner would be held for the
  //     remaining ~45 minutes of a dead game.
  //
  // A player is active in a round if they sent a message or made the selection.
  // The game ends when ANY player has been silent for maxTimeout rounds, which
  // frees the partner promptly while never punishing a pair who are both trying.
  const chat = round.get("chat");
  const messages = Array.isArray(chat) ? chat : (chat ? [chat] : []);
  const senders = new Set(
    messages.map((m) => (m && m.sender && m.sender.id) || null).filter(Boolean)
  );
  const selectedBy = currentSelection !== '' ? round.get("matcher") : null;

  players.forEach((player) => {
    const acted = senders.has(player.id) || player.id === selectedBy;
    const prior = player.get("roundsInactive") || 0;
    player.set("roundsInactive", acted ? 0 : prior + 1);
  });

  const perPlayerInactive = players.map((p) => p.get("roundsInactive") || 0);
  const worstInactive = perPlayerInactive.length ? Math.max(...perPlayerInactive) : 0;
  const messageCount = messages.length;

  // Kept for continuity with Exp 1 exports; the decision now uses worstInactive.
  game.set("numRoundsInactive", worstInactive);

  console.log(`Game ${game.id} - ${round.get("trialNum")}/${round.get("numTrials")}`);
  console.log(
    `- target: "${target}", selection: "${currentSelection}", ` +
    `messages: ${messageCount}, inactive per player: ${JSON.stringify(perPlayerInactive)}`
  );

  if (worstInactive >= game.get("maxTimeout")) {
    if (!game.get("ended")) {
      console.log(
        `Marking Game ${game.id} as ended: a player has been inactive for ` +
        `${worstInactive} rounds (per-player counts ${JSON.stringify(perPlayerInactive)})`
      );
      game.set("endedInactive", true);
      game.end("ended", "timeOut");
    }
  }

  // Save outcomes as property of round for later export/analysis
  round.set('response', round.get('selection'));
  round.set('correct', target === round.get('selection'));
});

Empirica.onGameEnded(({ game }) => {
  // Gate for the post-test exit step: only dyads that actually got through
  // training have anything to post-test on. A game killed by the inactivity
  // timeout sends its players straight to the incomplete survey instead.
  const done = game.get("trainingRoundsCompleted") || 0;
  const expected =
    (game.get("treatment")?.numRepetitionsWithPartner || 0) * (game.get("targets") || []).length;
  const completed = !game.get("endedInactive") && expected > 0 && done >= expected;
  game.players.forEach((player) => player.set("finishedTraining", completed));
  game.set("trainingRoundsExpected", expected);
  console.log(
    `Game ${game.id} ended; training ${done}/${expected}, endedInactive=` +
    `${game.get("endedInactive")} -> finishedTraining=${completed}`
  );

  // Refund the stimulus-set slot for games that did not produce usable data, so
  // a failed dyad does not permanently consume that set's capacity. Games that
  // completed keep their slot.
  if (completed) return;
  const released = releaseSet(game, empiricaCtx?.globals);
  console.log(
    `Game ${game.id} ended inactive; set ${game.get("setId")} slot ` +
    (released ? "released for reuse" : "NOT released (no tally entry)")
  );
});