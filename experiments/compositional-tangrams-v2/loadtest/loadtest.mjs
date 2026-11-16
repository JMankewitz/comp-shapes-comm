#!/usr/bin/env node
// Bot-driven load test for the Exp 2 Empirica server.
//
// WHY THIS EXISTS
// ---------------
// Empirica runs every server-side callback for every game through ONE global
// mutex (Cake.mutex in @empirica/core admin), and after each callback it waits
// for the database to acknowledge that callback's writes before the next one
// can start. The whole study is therefore a single lane. Its throughput, not CPU
// or RAM, sets how many games can run at once -- and nothing in the stack
// reports that ceiling. This harness measures it: scripted participants play
// real games against a real server while it times the two chains that live
// entirely inside the lane:
//
//   click_to_feedback   matcher's click -> stage flips to "feedback"
//   feedback_to_next    "feedback" appears -> next round's "selection" appears,
//                       minus the feedback stage's own duration
//
// On a healthy server both are tens of milliseconds. In a saturated lane they
// grow with the number of concurrent games.
//
// Bots reproduce what the real client WRITES (Tangram.jsx, Task.jsx, Game.jsx,
// Describe.jsx, intro steps), because writes are what load the lane. They do
// not render anything, so hundreds are cheap.
//
// USAGE (run against a server you started yourself; never against a live study)
//   node loadtest.mjs --root <project dir with client/ and server/ node_modules>
//        --url http://localhost:3099/query --games 12 --reps 1 --speed 1
//
// See --help for all options.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";

// ---------------------------------------------------------------- arguments
const argv = process.argv.slice(2);
const opt = {
  root: ".",
  url: "http://localhost:3099/query",
  token: "qbZHMNXAbXTduJxq",
  games: 6,          // total games across the three conditions
  reps: 1,           // numRepetitionsWithPartner; 1 => 12 training rounds, 4 => 48
  speed: 1,          // divides human think times. 1 = realistic, 10 = stress
  rampSec: 20,       // spread bot arrivals over this long
  accuracy: 0.92,
  maxTimeout: 5,       // inactivity rounds before a game ends (production now 10)
  pretestItemMs: 800,  // per-item pretest delay (real: ~40s; only a write load here)
  maxSec: 1500,
  out: "",
  label: "run",
};
const help = () => {
  console.log(fs.readFileSync(new URL(import.meta.url), "utf8").split("\n").slice(0, 38).join("\n"));
  process.exit(0);
};
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--help" || a === "-h") help();
  if (!a.startsWith("--")) continue;
  const k = a.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  if (!(k in opt)) { console.error(`unknown option ${a}`); process.exit(2); }
  const v = argv[++i];
  opt[k] = typeof opt[k] === "number" ? Number(v) : v;
}
const root = path.resolve(opt.root);

// ------------------------------------------------- browser shim, then imports
// The player library chooses its session storage at import time by checking for
// a browser `window`. One shared in-memory localStorage is enough: session keys
// are namespaced per participant.
const mem = new Map();
globalThis.window = {
  document: {},
  localStorage: {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: (k) => mem.delete(k),
    clear: () => mem.clear(),
  },
};
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { ParticipantContext } = await imp("client/node_modules/@empirica/core/dist/chunk-UMPSA52E.js");
const { EmpiricaClassic, TajribaProvider } = await imp("client/node_modules/@empirica/core/dist/player-classic.js");
// The admin ESM build (compiled by esbuild) falls back to a global `require` for
// Node built-ins, which plain Node ESM does not define. Provide one before
// importing it. (The package's CommonJS build is not an option: @empirica/tajriba
// declares an ESM-only "exports" map.)
globalThis.require = createRequire(import.meta.url);
const { AdminContext } = await imp("server/node_modules/@empirica/core/dist/admin.js");
const { classicKinds } = await imp("server/node_modules/@empirica/core/dist/admin-classic.js");

// ------------------------------------------------------------------ helpers
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rnd = (lo, hi) => lo + Math.random() * (hi - lo);
const think = (lo, hi) => (rnd(lo, hi) * 1000) / opt.speed;
const now = () => Date.now();
const pct = (arr, p) => {
  if (!arr.length) return NaN;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
};
async function waitFor(fn, ms, what) {
  const t0 = now();
  while (!fn()) {
    if (now() - t0 > ms) throw new Error(`timeout waiting for ${what}`);
    await sleep(50);
  }
}
const runId = Math.random().toString(16).slice(2, 8);
const events = []; // {t, bot, game, role, round, kind}
let botsFinished = 0;
let botsFailed = 0;

// --------------------------------------------------------------------- bot
class Bot {
  constructor(i, url) {
    this.i = i;
    this.url = url;
    this.key = `bot${runId}${String(i).padStart(4, "0")}`;
    this.rounds = new Map();
    this.done = false;
    this.introDone = false;
    this.pre = null;
    this.trainStarted = false;
    this.gameSoundSet = false;
  }

  async start() {
    this.ctx = new ParticipantContext(this.url, this.key);
    await waitFor(() => this.ctx.tajriba.connected.getValue() === true, 30000, "tajriba connect");
    await this.ctx.register(this.key);
    await waitFor(
      () => this.ctx.provider.getValue() && this.ctx.participant.participant.getValue(),
      30000, "provider"
    );
    const part = this.ctx.participant.participant.getValue();
    // The provider ParticipantContext builds on its own never receives changes
    // when driven headless (its changes() subscription starts too early; browsers
    // evidently get away with it). Building a fresh one once the connection has
    // settled is reliable, and is the same construction the library does.
    await sleep(300);
    const provider = new TajribaProvider(
      part.changes(), this.ctx.tajriba.tajriba.globalAttributes(), part.setAttributes.bind(part));
    this.mode = EmpiricaClassic(part.id, provider);
    this.timer = setInterval(() => { try { this.tick(); } catch (e) { this.fail(e); } }, 150);
  }

  fail(e) {
    if (this.done) return;
    botsFailed++;
    console.error(`bot ${this.key}:`, e && e.message ? e.message : e);
    this.stop();
  }

  stop() {
    if (this.done) return;
    this.done = true;
    clearInterval(this.timer);
    botsFinished++;
    try { this.ctx.stop(); } catch (_) { /* already closed */ }
  }

  log(kind, round, extra = {}) {
    events.push({ t: now(), bot: this.i, game: this.gameID, role: this.role, trial: round?.get("trialNum"), kind, ...extra });
  }

  tick() {
    if (this.done) return;
    const player = this.mode.player.getValue();
    if (!player || !player.get("gameID")) return;
    this.gameID = player.get("gameID");

    // Intro: the real client ends its intro steps by setting introDone.
    if (!this.introDone) {
      this.introDone = true;
      setTimeout(() => {
        player.set("aiAgreement", { agreed: true, at: now() });
        player.set("introDone", true);
      }, think(1, 3));
      return;
    }

    const game = this.mode.game.getValue();
    const round = this.mode.round.getValue();
    const stage = this.mode.stage.getValue();
    if (game && game.hasEnded) { this.log("game_end", round); this.stop(); return; }
    if (!game || !round || !stage) return;

    const phase = round.get("phase");
    if (phase === "pretest") this.pretest(player, round, stage);
    else if (phase === "training") this.training(player, game, round, stage);
  }

  // Describe.jsx / Game.jsx pre-test writes.
  pretest(player, round, stage) {
    if (this.pre) return;
    this.pre = { i: 0 };
    player.set("pretestCardShownAt", now());
    setTimeout(() => player.set("pretestStarted", true), think(1, 3));
    const items = player.get("pretestItems") || [];
    const step = () => {
      if (this.done) return;
      const i = this.pre.i;
      if (i >= items.length) {
        player.set("pretestSubmittedAt", now());
        player.stage.set("submit", true);
        return;
      }
      const it = items[i];
      const prior = player.get("pretestResponses") || [];
      player.set("pretestResponses", [...prior, {
        image: it.image, label: it.label, cell: it.cell, top: it.top, bottom: it.bottom,
        order: i, text: "a bot described this shape", shownAt: now() - 1000,
        submittedAt: now(), autoSubmitted: false, pasteAttempts: 0,
      }], { private: true });
      player.set("pretestProgress", prior.length + 1);
      this.pre.i++;
      setTimeout(step, opt.pretestItemMs * rnd(0.6, 1.4));
    };
    setTimeout(step, think(2, 4) + 500);
  }

  // Task.jsx / Tangram.jsx / Game.jsx training-round writes.
  training(player, game, round, stage) {
    const sname = stage.get("name");
    const rid = round.id;
    let st = this.rounds.get(rid);
    if (!st) { st = { sel: 0, fb: false, acted: false }; this.rounds.set(rid, st); }
    this.role = player.get("role");

    // Game.jsx: whoever sees justStarted clears it (both clients do).
    if (round.get("justStarted")) round.set("justStarted", false);
    if (!this.gameSoundSet && game.get("justStarted")) { this.gameSoundSet = true; game.set("justStarted", false); }

    if (!this.trainStarted) { this.trainStarted = true; player.set("trainingStartedAt", now()); }

    if (sname === "selection" && !st.sel) {
      st.sel = now();
      this.log("sel", round);
      setTimeout(() => { if (!this.done) player.round && player.round.set("renderedAt", now()); }, rnd(50, 300));
    }
    if (sname === "feedback" && !st.fb) { st.fb = true; this.log("fb", round); }
    if (sname !== "selection" || st.acted) return;

    const partnerID = player.get("partner");
    const chat = round.get("chat") || [];
    if (this.role === "director") {
      st.acted = true;
      setTimeout(() => {
        if (this.done) return;
        round.append("chat", { text: "the one with the pointy bit", sender: { id: player.id, name: player.get("name") || player.id, avatar: player.get("avatar") } });
        this.log("chat", round);
      }, think(8, 18));
    } else if (chat.some((m) => m?.sender?.id === partnerID)) {
      st.acted = true;
      setTimeout(() => {
        if (this.done) return;
        const urls = round.get("tangramURLs") || [];
        const target = round.get("target");
        const wrong = urls.filter((u) => u !== target);
        const pick = Math.random() < opt.accuracy || !wrong.length ? target : wrong[Math.floor(Math.random() * wrong.length)];
        const players = this.mode.players.getValue() || [];
        const partner = players.find((p) => p.id === partnerID);
        this.log("click", round);
        round.set("selectionMadeAt", now());
        round.set("selection", pick);
        player.stage.set("submit", true);
        if (partner && partner.stage) partner.stage.set("submit", true);
      }, think(4, 12));
    }
  }
}

// -------------------------------------------------------------- batch setup
async function createBatch() {
  const tokenPath = path.join(os.tmpdir(), `loadtest-token-${runId}`);
  const ctx = await AdminContext.init(opt.url, tokenPath, `loadtest-${runId}`, opt.token, {}, classicKinds);
  const conds = ["comp-within", "comp-between", "noncomp"];
  const per = Math.max(1, Math.round(opt.games / conds.length));
  const treatments = conds.map((c) => ({
    count: per,
    treatment: {
      name: `loadtest-${c}`,
      factors: {
        contextSize: 4, contextStructure: c, describeSecondsPerItem: 60, feedbackDuration: 3,
        maxTimeout: opt.maxTimeout, numRepetitionsWithPartner: opt.reps, playerCount: 2,
        selectionDuration: 60, showNegativeFeedback: 1,
      },
    },
  }));
  const lobby = { kind: "individual", duration: 10 * 60 * 1e9, strategy: "ignore" }; // ns
  const attr = (key, value, extra = {}) => ({ key, val: JSON.stringify(value), ...extra });
  let created;
  const ready = new Promise((resolve, reject) => {
    ctx.register(function (_) {
      _.on("ready", async (c) => {
        try {
          created = await c.addScopes([{
            kind: "batch",
            attributes: [
              attr("config", { kind: "complete", config: { treatments } }, { immutable: true }),
              attr("lobbyConfig", lobby),
              attr("status", "running"),
              attr("name", `loadtest-${runId}`),
              attr("initialized", false),
            ],
          }]);
          resolve();
        } catch (e) { reject(e); }
      });
    });
  });
  await ready;
  console.log(`batch created: ${per * 3} games (${per}/condition), ${opt.reps * 12} training rounds each`);
  return ctx;
}

// ------------------------------------------------------------------ report
function report(nBots, elapsedSec) {
  const byGame = new Map();
  for (const e of events) {
    if (!byGame.has(e.game)) byGame.set(e.game, []);
    byGame.get(e.game).push(e);
  }
  const click2fb = [], fb2next = [], roundWall = [];
  let roundsDone = 0;
  const fbDur = 3000;
  for (const [, evs] of byGame) {
    // per bot, per trial
    const byBot = new Map();
    for (const e of evs) {
      if (e.trial === undefined) continue;
      const k = `${e.bot}`;
      if (!byBot.has(k)) byBot.set(k, new Map());
      const m = byBot.get(k);
      if (!m.has(e.trial)) m.set(e.trial, {});
      m.get(e.trial)[e.kind] = e.t;
    }
    for (const [, m] of byBot) {
      const trials = [...m.keys()].sort((a, b) => a - b);
      for (const t of trials) {
        const r = m.get(t), nx = m.get(t + 1);
        if (r.click && r.fb) click2fb.push(r.fb - r.click);
        if (r.fb && nx && nx.sel) fb2next.push(nx.sel - r.fb - fbDur);
        if (r.sel && nx && nx.sel) roundWall.push(nx.sel - r.sel);
        if (r.fb) roundsDone++;
      }
    }
  }
  // rounds are seen by 2 bots; count distinct (game,trial)
  const distinct = new Set(events.filter((e) => e.kind === "fb").map((e) => `${e.game}:${e.trial}`)).size;
  const f = (a, p) => (Number.isFinite(pct(a, p)) ? Math.round(pct(a, p)) : "-");
  const rows = {
    label: opt.label, games: opt.games, bots: nBots, reps: opt.reps, speed: opt.speed,
    elapsed_s: Math.round(elapsedSec), distinct_rounds_completed: distinct,
    rounds_per_min: +(distinct / (elapsedSec / 60)).toFixed(1),
    click_to_feedback_ms: { n: click2fb.length, p50: f(click2fb, 50), p90: f(click2fb, 90), p99: f(click2fb, 99) },
    feedback_to_next_ms:  { n: fb2next.length,  p50: f(fb2next, 50),  p90: f(fb2next, 90),  p99: f(fb2next, 99) },
    round_wall_ms:        { n: roundWall.length, p50: f(roundWall, 50), p90: f(roundWall, 90), p99: f(roundWall, 99) },
    bots_failed: botsFailed,
  };
  return rows;
}

// -------------------------------------------------------------------- main
const t0 = now();
const adminCtx = await createBatch();
const nBots = opt.games * 2;
const bots = [];
console.log(`starting ${nBots} bots over ${opt.rampSec}s (run ${runId})`);
for (let i = 0; i < nBots; i++) {
  const b = new Bot(i, opt.url);
  bots.push(b);
  b.start().catch((e) => b.fail(e));
  await sleep((opt.rampSec * 1000) / nBots);
}
const tPlay0 = now();
let lastPrint = 0;
while (botsFinished < nBots && now() - t0 < opt.maxSec * 1000) {
  await sleep(1000);
  if (now() - lastPrint > 15000) {
    lastPrint = now();
    const fbs = new Set(events.filter((e) => e.kind === "fb").map((e) => `${e.game}:${e.trial}`)).size;
    console.log(`  t+${Math.round((now() - t0) / 1000)}s  bots done ${botsFinished}/${nBots}  rounds completed ${fbs}`);
  }
}
const elapsed = (now() - tPlay0) / 1000;
const rep = report(nBots, elapsed);
console.log("\n" + JSON.stringify(rep, null, 2));
if (opt.out) fs.writeFileSync(opt.out, JSON.stringify({ opt, rep, events }, null, 0));
for (const b of bots) b.stop();
try { adminCtx.stop && (await adminCtx.stop()); } catch (_) { /* ignore */ }
process.exit(botsFinished >= nBots ? 0 : 3);
