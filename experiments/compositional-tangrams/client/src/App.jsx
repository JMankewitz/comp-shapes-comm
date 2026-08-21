import { EmpiricaClassic } from "@empirica/core/player/classic";
import { EmpiricaContext } from "@empirica/core/player/classic/react";
import { EmpiricaMenu, EmpiricaParticipant } from "@empirica/core/player/react";
import React from "react";
import { Game } from "./Game";
import { ExitSurvey } from "./intro-exit/ExitSurvey";
import { IncompleteExitSurvey } from "./intro-exit/IncompleteExitSurvey";
import { NoGameSurvey } from "./intro-exit/NoGameExitSurvey";

import { Introduction } from "./intro-exit/Introduction";
import {Consent} from "./intro-exit/Consent"
import { MyPlayerForm } from "./intro-exit/PlayerCreate.jsx";

import {Quiz} from "./intro-exit/Quiz";
import { Posttest } from "./intro-exit/Posttest";
export default function App() {
  const urlParams = new URLSearchParams(window.location.search);
  const playerKey = urlParams.get("participantKey") || "";

  const { protocol, host } = window.location;
  const url = `${protocol}//${host}/query`;

  function introSteps({ game, player }) {
    return [Consent, Introduction, Quiz];
    //return [Consent];

  }

  function exitSteps({ game, player }) {
    // Empirica sets player `ended` to "game ended" on a NORMAL finish too, so the
    // old first branch caught every completing participant and showed them the
    // "you were disconnected" survey. And `endedInactive` was only ever written
    // at GAME scope (callbacks.js), so `player.get('endedInactive')` was always
    // undefined -- that clause never fired at all.
    //
    // Route on `finishedTraining`, which onGameEnded sets only for games that
    // were not killed by the inactivity timeout -- not on Empirica's end-reason
    // strings. The post-test runs here rather than as a game round, so each
    // participant works through it at their own pace and leaves without waiting
    // on their partner.
    if (player.get("finishedTraining")) {
      return [Posttest, ExitSurvey];
    }
    // Reached a game but it ended early: inactivity timeout, or partner dropout.
    if (player.get("ended") || game?.get("endedInactive")) {
      return [IncompleteExitSurvey];
    }
    // Never matched into a game at all.
    return [NoGameSurvey];
  }

  return (
    <EmpiricaParticipant url={url} ns={playerKey} modeFunc={EmpiricaClassic}>
      <div className="h-screen relative">
        <EmpiricaMenu position="bottom-left" />
        <div className="h-full overflow-auto">
          <EmpiricaContext playerCreate={MyPlayerForm} introSteps={introSteps} 
          exitSteps={exitSteps}>
            <Game />
          </EmpiricaContext>
        </div>
      </div>
    </EmpiricaParticipant>
  );
}
