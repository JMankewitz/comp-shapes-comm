import { EmpiricaClassic } from "@empirica/core/player/classic";
import { EmpiricaContext } from "@empirica/core/player/classic/react";
import { EmpiricaMenu, EmpiricaParticipant } from "@empirica/core/player/react";
import React from "react";
import { Game } from "./Game";
import { ExitSurvey } from "./intro-exit/ExitSurvey";
import { IncompleteExitSurvey } from "./intro-exit/IncompleteExitSurvey";

import { Introduction } from "./intro-exit/Introduction";
import {Consent} from "./intro-exit/Consent"

import {Quiz} from "./intro-exit/Quiz";
export default function App() {
  const urlParams = new URLSearchParams(window.location.search);
  const playerKey = urlParams.get("participantKey") || "";

  const { protocol, host } = window.location;
  const url = `${protocol}//${host}/query`;

  function introSteps({ game, player }) {
    return [Consent, Introduction, Quiz];
  }

  function exitSteps({ game, player }) {
    if (player.get('ended') === "timeOut") {
      return [IncompleteExitSurvey];
    }
    else {
      return [ExitSurvey];
    }
  }

  return (
    <EmpiricaParticipant url={url} ns={playerKey} modeFunc={EmpiricaClassic}>
      <div className="h-screen relative">
        <EmpiricaMenu position="bottom-left" />
        <div className="h-full overflow-auto">
          <EmpiricaContext introSteps={introSteps} 
          exitSteps={exitSteps}>
            <Game />
          </EmpiricaContext>
        </div>
      </div>
    </EmpiricaParticipant>
  );
}
