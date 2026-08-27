import { AdminContext } from "@empirica/core/admin";
import {
  Classic,
  classicKinds,
  ClassicLoader,
  Lobby,
} from "@empirica/core/admin/classic";
import { info, setLogLevel } from "@empirica/core/console";
import minimist from "minimist";
import process from "process";
import { Empirica } from "./callbacks";

const argv = minimist(process.argv.slice(2), { string: ["token"] });

setLogLevel(argv["loglevel"] || "info");

(async () => {
  // The callbacks connect back to the Empirica server over websocket. This URL
  // used to be hardcoded to port 3000, which breaks whenever the server runs
  // anywhere else: `empirica serve --addr :3001` moves the LISTENER but does not
  // pass --url through to the callbacks, so they kept dialing 3000. On a shared
  // host that is somebody else's app, and the handshake fails with a 404 on
  // /query. Honour --url first, then EMPIRICA_PORT, then the old default.
  const callbacksURL =
    argv["url"] ||
    process.env.EMPIRICA_CALLBACKS_URL ||
    `http://localhost:${process.env.EMPIRICA_PORT || "3000"}/query`;

  info(`callbacks: connecting to ${callbacksURL}`);

  const ctx = await AdminContext.init(
    callbacksURL,
    argv["sessionTokenPath"],
    "callbacks",
    argv["token"],
    {},
    classicKinds
  );

  ctx.register(ClassicLoader);

  // preferUnderassignedGames does NOT concentrate arrivals. Verified against
  // @empirica/core dist (assignPlayer):
  //
  //   const filteredGames = availableGames.filter(g => g.players.length < playerCount);
  //   ...
  //   const game = pickRandom(availableGames);
  //
  // It filters out games that are already FULL, then picks at RANDOM among the
  // rest. A game holding one waiting player ranks no higher than an untouched
  // one. So it prevents overbooking; it does nothing to pair people up.
  //
  // The real lever is HOW MANY GAMES ARE OPEN AT ONCE. Arrivals scatter across
  // whatever games exist, so a pool much larger than the number of concurrent
  // participants produces games holding one player each, all of whom wait the
  // full lobby duration and then time out. Aim for open games per condition
  // ~= half the expected concurrent participants per condition, and start extra
  // batches only as the running ones fill. A batch contributes its games as
  // soon as it is STARTED, so a reserve batch must be left unstarted.
  //
  // neverOverbookGames ON. Batches are walked IN ORDER and the loop returns on
  // the first assignment, so batch 2 is only reached when batch 1 has no
  // assignable games -- a reserve batch does work as a reserve. But when every
  // game in batch 1 is full-but-unstarted, filteredGames is empty and the
  // default is to OVERBOOK within batch 1 rather than move on:
  //
  //   if (filteredGames.length === 0) {
  //     if (neverOverbookGames) { availableGames = []; }  // -> continue, next batch
  //     else { /* overbook */ }
  //   }
  //
  // Setting it empties availableGames, which hits `continue` and flows surplus
  // players into the overflow batch instead of stuffing them into full games.
  //
  // It also matches the payment policy: once every batch is exhausted a player
  // gets `ended = "no more games"` and is turned away at $0-$1, rather than
  // being assigned to a game that cannot start and timing out at $2.50.
  //
  // Cost: overbooking was the cheap insurance for someone abandoning during the
  // intro steps. That is still covered -- an abandoned seat leaves the game
  // non-full, so the next arrival fills it; it just is not pre-staffed.
  ctx.register(Classic({
    preferUnderassignedGames: true,
    neverOverbookGames: true,
  }));
  ctx.register(Lobby());
  ctx.register(Empirica);
  ctx.register(function (_) {
    _.on("ready", function () {
      info("server: started");
    });
  });
})();

process.on("unhandledRejection", function (reason, p) {
  process.exitCode = 1;
  console.error("Unhandled Promise Rejection. Reason: ", reason);
});
