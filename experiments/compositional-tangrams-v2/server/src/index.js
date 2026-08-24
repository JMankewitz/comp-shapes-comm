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
  ctx.register(Classic());
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
