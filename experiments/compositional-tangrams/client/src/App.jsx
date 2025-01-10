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
    console.log("Player ended status:", player.get('ended'));
    //console.log("game ended reason:", game.get("endedReason"))
    if (player.get('ended') === "game ended" || player.get('endedInactive')){
      return [IncompleteExitSurvey];
    }
    else {
      return [NoGameSurvey];
    }
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
