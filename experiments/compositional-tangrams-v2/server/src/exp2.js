// Experiment 2 support: stimulus-set loading, set assignment, display construction.
//
// Design doc: documents/journal-revision-design.md, S4.
//
// LABEL COLLISION -- read before touching this file.
// In exp2_comp_sets.json, "F" is a novel TOP component, so F2 = top F + bottom 2.
// In exp2_noncomp_sets.json, F1-F8 are FILLER WHOLES, so F2 = the second filler
// whole and has nothing to do with any component "F". Worse, the collision is
// intra-file: a noncomp set's training_shapes contain the filler F2 while its
// posttest_items contain the component-composed F2, and they are different
// images. Nothing here parses labels -- match on `top`/`bottom`/`image` only.
// Labels are carried through to the data purely as analysis annotations.

import _ from "lodash";
import { promises as fs } from "fs";
import { join } from "path";

const SET_FILE_BY_CONDITION = {
  noncomp: "exp2_noncomp_sets.json",
  "comp-within": "exp2_comp_sets.json",
  "comp-between": "exp2_comp_sets.json",
};

const SCHEDULE_FILE = "exp2_set_schedule.json";

// Data-file lookup must not depend on cwd.
//
// `npm run build` rsyncs every non-.js file from src/ into dist/, next to the
// bundle. But the two run scripts use different working directories:
//   dev   -> `node dist/index.js`  from server/      => cwd is server/
//   serve -> `node index.js`       from server/dist/ => cwd is server/dist/
// A bare relative filename therefore resolves in production and ENOENTs in dev,
// which is why Exp 1's `comp_sets.json` appeared to work. Probe both, plus src/
// for anyone running the callbacks unbundled, and remember which one won.
const CANDIDATE_DIRS = [
  // Directory of the bundle itself, when the output format provides it.
  typeof __dirname !== "undefined" ? __dirname : null,
  "dist",
  ".",
  "src",
  "server/src",
];

let _resolvedDir = null;

async function resolveDataFile(filename) {
  if (_resolvedDir !== null) return join(_resolvedDir, filename);
  for (const dir of CANDIDATE_DIRS) {
    if (dir === null) continue;
    const candidate = join(dir, filename);
    try {
      await fs.access(candidate);
      _resolvedDir = dir;
      console.log(`Exp 2 data files resolved from "${dir}" (cwd ${process.cwd()})`);
      return candidate;
    } catch {
      // try the next candidate
    }
  }
  throw new Error(
    `Could not locate ${filename}. Looked in ${CANDIDATE_DIRS.filter(Boolean)
      .map((d) => `"${d}"`)
      .join(", ")} relative to cwd ${process.cwd()}. ` +
      `If this is a fresh checkout, run \`npm run build\` in server/ to rsync ` +
      `the .json stimulus files into dist/.`
  );
}

// 4.3 MB of JSON per file; parse once per server process, not once per game.
const _fileCache = new Map();

async function loadJSON(filename) {
  if (!_fileCache.has(filename)) {
    const path = await resolveDataFile(filename);
    _fileCache.set(filename, JSON.parse(await fs.readFile(path, "utf8")));
  }
  return _fileCache.get(filename);
}

export async function loadSchedule() {
  const schedule = await loadJSON(SCHEDULE_FILE);
  if (schedule.schema_version !== "exp2-schedule-1") {
    throw new Error(
      `${SCHEDULE_FILE}: unexpected schema_version ${schedule.schema_version}`
    );
  }
  return schedule;
}

export async function loadSet(condition, setId) {
  const filename = SET_FILE_BY_CONDITION[condition];
  if (!filename) throw new Error(`no Exp 2 stimulus file for condition ${condition}`);
  const doc = await loadJSON(filename);
  const set = doc.sets.find((s) => s.set_id === setId);
  if (!set) throw new Error(`${filename}: no set with set_id ${setId}`);
  return set;
}

// ---------------------------------------------------------------------------
// Set assignment (S4.8)
//
// Target allocation is 2 dyads per condition per stimulus set.
//
// The tally lives in Empirica's GLOBAL scope, not in the batch. Recruitment runs
// one batch per game per condition (Empirica's recommended pattern for correct
// game assignment), so a per-batch tally would never see a sibling and every
// dyad would land on set 0. Globals persist across batches and across server
// restarts, which is what this allocation needs.
//
// Shape: { "<condition>": { "<setId>": <dyads> } }
//
// Assignment is a claim: pick the set with the fewest dyads for this condition,
// increment it, write it back. A game that later dies to inactivity refunds its
// slot in onGameEnded, so failed games do not permanently consume capacity.
//
// When every set has its full complement we WRAP rather than turn players away
// (decision 2026-08): the tally keeps climbing and `replicate` increments, so
// sets pick up a 3rd and 4th dyad instead of arrivals being rejected. Every game
// records setId, condition and replicate, so pairing dyads post hoc is a
// group_by(set_id, condition) -- with `replicate` available if a balanced
// 2-per-set subset is wanted.
// ---------------------------------------------------------------------------

const TALLY_KEY = "exp2SetTally";

/** Read the {setId: count} map for one condition, zero-filled over the schedule. */
function conditionCounts(allTallies, condition, setIds) {
  const stored = allTallies[condition] || {};
  const counts = {};
  for (const sid of setIds) counts[sid] = stored[sid] ?? 0;
  return counts;
}

export function assignSet(game, schedule, globals) {
  const condition = game.get("contextStructure");
  const setIds = schedule.set_ids;
  const perSet = schedule.dyads_per_condition_per_set;

  if (!globals) {
    // Never fail silently here: without the tally every dyad gets set 0 and the
    // whole flat allocation quietly collapses.
    throw new Error(
      `Game ${game.id}: Empirica globals unavailable, cannot assign a stimulus ` +
      `set. The global tally is the only cross-batch record of allocation; ` +
      `assigning without it would put every dyad on set ${setIds[0]}.`
    );
  }

  const allTallies = globals.get(TALLY_KEY) || {};
  const counts = conditionCounts(allTallies, condition, setIds);

  // DEPTH-FIRST: finish a set before opening the next one.
  //
  // The unit of analysis is the PAIR -- a set with one dyad contributes nothing
  // to the between-dyad comparison (S4.8, DV6), which is the chance level that
  // makes DV1 and DV5 interpretable. Filling breadth-first (always take the
  // least-filled set) would give every set one dyad before any set got two, so
  // an 8-set pool yields zero usable pairs until dyad 9 -- and a 75-set pool run
  // at pilot size would yield zero pairs, ever.
  //
  // Depth-first makes the allocation robust to the pool being larger than the
  // run: every completed prefix of the run maximises complete pairs, and the
  // final tally is identical once the run fills.
  let chosen = setIds.find((sid) => counts[sid] < perSet);

  // Every set full: wrap. Fall back to least-filled so the extra dyads spread
  // evenly rather than piling onto set 0.
  if (chosen === undefined) {
    chosen = setIds[0];
    for (const sid of setIds) {
      if (counts[sid] < counts[chosen]) chosen = sid;
    }
  }
  const priorDyads = counts[chosen];

  // Claim the slot immediately -- the next game must see this.
  globals.set(TALLY_KEY, {
    ...allTallies,
    [condition]: { ...counts, [chosen]: priorDyads + 1 },
  });

  return {
    setId: chosen,
    setIndex: setIds.indexOf(chosen),
    replicate: Math.floor(priorDyads / perSet), // 0 = the primary pair, 1+ = wrap
    slotInReplicate: priorDyads % perSet,
    priorDyadsOnSet: priorDyads,
    wrapped: priorDyads >= perSet,
    tallyAfterClaim: { ...counts, [chosen]: priorDyads + 1 },
  };
}

/**
 * Give a set's slot back when a game fails, so it can be refilled. Without this,
 * a dyad that times out in round 3 would permanently cost that set a replicate.
 */
export function releaseSet(game, globals) {
  if (!globals) return false;
  const condition = game.get("contextStructure");
  const setId = game.get("setId");
  if (setId === undefined || setId === null) return false;

  const allTallies = globals.get(TALLY_KEY) || {};
  const stored = allTallies[condition] || {};
  const current = stored[setId] ?? 0;
  if (current <= 0) return false;

  globals.set(TALLY_KEY, {
    ...allTallies,
    [condition]: { ...stored, [setId]: current - 1 },
  });
  return true;
}

// ---------------------------------------------------------------------------
// Display construction (S4.2)
//
// Every shape in a display must be one of the 12 trained shapes. Shapes are the
// objects straight out of training_shapes: {label, top, bottom, image}.
// ---------------------------------------------------------------------------

const sameShape = (a, b) => a.top === b.top && a.bottom === b.bottom;

/**
 * Within-trial: target + one shape sharing its top + one sharing its bottom +
 * one trained shape sharing NO component with any of the other three.
 *
 * This replaces the old 2x2 rectangle, which the diagonal holdout collapsed to
 * 2 displays/target. Yields 14/target on the 4x4-minus-diagonal trained set --
 * more than the full 4x4's 9.
 *
 * The fourth shape is required to be disjoint from the two competitors as well
 * as from the target. That stricter reading is what reproduces the doc's 14; the
 * looser "disjoint from the target only" gives 28 and lets the fourth shape
 * incidentally share a component with a competitor, which muddies the contrast.
 */
export function withinTrialDisplays(target, trained) {
  const displays = [];
  const topSharers = trained.filter((s) => s.top === target.top && !sameShape(s, target));
  const bottomSharers = trained.filter(
    (s) => s.bottom === target.bottom && !sameShape(s, target)
  );

  for (const topSharer of topSharers) {
    for (const bottomSharer of bottomSharers) {
      const usedTops = new Set([target.top, topSharer.top, bottomSharer.top]);
      const usedBottoms = new Set([target.bottom, topSharer.bottom, bottomSharer.bottom]);
      for (const fourth of trained) {
        if (usedTops.has(fourth.top) || usedBottoms.has(fourth.bottom)) continue;
        displays.push([target, topSharer, bottomSharer, fourth]);
      }
    }
  }
  return displays;
}

/**
 * Across-trial: four trained shapes, no two of which share any component.
 *
 * The old code zipped 3 alternative tops against 3 alternative bottoms, which
 * can land on a held-out diagonal cell. Enumerating instead of retrying makes
 * the ~3 legal displays/target explicit rather than a sampling accident.
 */
export function acrossTrialDisplays(target, trained) {
  const displays = [];
  const candidates = trained.filter(
    (s) => s.top !== target.top && s.bottom !== target.bottom
  );

  for (let i = 0; i < candidates.length; i++) {
    for (let j = i + 1; j < candidates.length; j++) {
      for (let k = j + 1; k < candidates.length; k++) {
        const display = [target, candidates[i], candidates[j], candidates[k]];
        const tops = new Set(display.map((s) => s.top));
        const bottoms = new Set(display.map((s) => s.bottom));
        if (tops.size === display.length && bottoms.size === display.length) {
          displays.push(display);
        }
      }
    }
  }
  return displays;
}

/**
 * Non-compositional: the 12 trained wholes share no components by construction,
 * so any 3 distractors are legal. Enumerating all C(11,3) = 165 would be
 * wasteful; sample per block instead, matching Exp 1's behaviour.
 */
export function nonCompDisplay(target, trained, displaySize) {
  const distractors = _.sampleSize(
    trained.filter((s) => !sameShape(s, target)),
    displaySize - 1
  );
  return [target, ...distractors];
}

/**
 * Draws displays for one target across blocks without repeating until the pool
 * is exhausted. Within-trial has 14 legal displays and 4 blocks, so no dyad ever
 * sees the same display twice. Across-trial has only 3, so exactly one repeats
 * per target -- forced by the condition's definition (S4.2), not a bug.
 */
export function makeDisplayPicker(allDisplays) {
  if (!allDisplays.length) throw new Error("no legal displays for target");
  let pool = _.shuffle(allDisplays);
  let cursor = 0;
  return () => {
    if (cursor >= pool.length) {
      pool = _.shuffle(allDisplays);
      cursor = 0;
    }
    return pool[cursor++];
  };
}

export const imageURL = (shape) => `/tangrams/${shape.top}_${shape.bottom}.png`;

export const ROTATIONS = [0, 90, 180, 270];

/**
 * Rotation is a property of the STIMULUS SET, not of the game (changed 2026-08).
 *
 * It used to be `_.sample(ROTATIONS)` per game, so two dyads assigned the same
 * set could see the shapes at different orientations. That silently breaks S4.8:
 * the between-dyad comparison is defined as two dyads facing the *exact same
 * environment*, and a 90-degree difference is a different environment for
 * anything descriptions are built on ("pointy bit on the left"). It would also
 * contaminate the within-set between-condition contrast, since a comp-within and
 * a comp-between dyad on set N are supposed to be stimulus-matched.
 *
 * Deriving it from set_id keeps every dyad on a set -- in every condition --
 * seeing an identical display, while still spreading all four orientations
 * evenly across the set pool.
 */
export const rotationForSet = (setId) => ROTATIONS[setId % ROTATIONS.length];

/**
 * Shuffle an item list so no component reappears within `minGap` trials.
 *
 * A plain shuffle averages ~2.4 adjacent component-sharing pairs across the
 * 20-item test list, which puts e.g. A2 directly before A1 and hands the
 * participant the decomposition for free. S4.5 flags this leak -- exposure to
 * recurring components across trials is the across-trial CONDITION, so the
 * pre-test must not teach it -- and back-to-back repeats are its worst case.
 *
 * Greedy build with restarts, relaxing the gap only if the tighter one cannot be
 * satisfied. On the 20-item list k=4 succeeds ~18% of attempts (so effectively
 * always within 200 tries) and k=5 is not reliably satisfiable, since four tops
 * and four bottoms each appear 3 times in 20 trials. The achieved gap is
 * returned so it can be recorded per player rather than silently assumed.
 */
export function spacedShuffle(items, { minGap = 4, attempts = 200 } = {}) {
  const shares = (a, b) => a.top === b.top || a.bottom === b.bottom;

  for (let gap = minGap; gap >= 1; gap--) {
    for (let attempt = 0; attempt < attempts; attempt++) {
      const remaining = _.shuffle(items);
      const order = [];
      let stuck = false;
      while (remaining.length) {
        const recent = order.slice(-gap);
        const idx = remaining.findIndex((it) => !recent.some((r) => shares(r, it)));
        if (idx === -1) { stuck = true; break; }
        order.push(remaining.splice(idx, 1)[0]);
      }
      if (!stuck) return { order, gap };
    }
  }
  // Unreachable for the real item lists; never block a game on ordering.
  console.warn("spacedShuffle: no spaced ordering found, falling back to plain shuffle");
  return { order: _.shuffle(items), gap: 0 };
}

/** Attach the client-facing URL so the description phase needs no path logic. */
export const withURLs = (items) => items.map((it) => ({ ...it, url: imageURL(it) }));

/**
 * One round, one stage, per test phase (S4.5).
 *
 * The item list is iterated CLIENT-SIDE and each player calls
 * player.stage.set("submit", true) when they finish their own list, so the two
 * partners never block each other. Phase duration is max(A, B), not the sum.
 *
 * `duration` is only a safety cap for an abandoned tab -- under normal play both
 * players submit long before it fires. It scales with item count because the
 * noncomp pre-test is 8 items, not 20 (S4.6).
 */
export function addDescribeRound(game, phase, numItems, treatment) {
  // Per-ITEM allowance, enforced client-side with autosubmit (Describe.jsx).
  // S6.3 estimates ~25s per item, so 60 is generous without letting one stalled
  // participant hold their partner indefinitely. Bounding the item rather than
  // the phase means a slow start cannot eat the whole budget.
  const perItem = treatment.describeSecondsPerItem ?? 60;
  const round = game.addRound({
    phase,
    numItems,
    // No target, no tangramURLs, no foils, no matcher, no feedback, no accuracy.
    // An earlier design had arrays and a matcher here; they were deliberately
    // removed (S4.3). Do not add them back.
    target: "",
    tangramURLs: [],
  });
  // Backstop only. The client autosubmits each item, so the phase completes in
  // at most numItems * perItem on its own; the extra 5 minutes covers reading the
  // interstitial cards, which sit outside the per-item clocks.
  round.addStage({ name: "describe", duration: numItems * perItem + 300 });
  return round;
}
