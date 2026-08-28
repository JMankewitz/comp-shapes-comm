import { EmpiricaClassic } from "@empirica/core/player/classic";
import { EmpiricaContext } from "@empirica/core/player/classic/react";
import { EmpiricaMenu, EmpiricaParticipant } from "@empirica/core/player/react";
import React from "react";
import { Game } from "./Game";
import { ExitSurvey } from "./intro-exit/ExitSurvey";
import { IncompleteExitSurvey } from "./intro-exit/IncompleteExitSurvey";
import { NoGameSurvey } from "./intro-exit/NoGameExitSurvey";
import { LobbyExitSurvey } from "./intro-exit/LobbyExitSurvey";
import { exitTier } from "./tiers";
import { AIAgreement } from "./intro-exit/AIAgreement";
import { AIDisclosure } from "./intro-exit/AIDisclosure";

import { Introduction } from "./intro-exit/Introduction";
import {Consent} from "./intro-exit/Consent"
import { MyPlayerForm } from "./intro-exit/PlayerCreate.jsx";

import {Quiz} from "./intro-exit/Quiz";
import { Posttest } from "./intro-exit/Posttest";
import { Finished } from "./intro-exit/Finished";
export default function App() {
  const urlParams = new URLSearchParams(window.location.search);
  const playerKey = urlParams.get("participantKey") || "";

  const { protocol, host } = window.location;
  const url = `${protocol}//${host}/query`;

  function introSteps({ game, player }) {
    // AIAgreement sits with the consent, not after the quiz. It belongs to the
    // same act: telling people what we need from them and what they are
    // contributing, before they invest any effort. Placing it at the end read as
    // a compliance gate on the way to the task; here it reads as part of the
    // agreement to take part.
    //
    // It also keeps `introDone` meaning what it did. As a post-quiz step it
    // would have moved the finish line, so someone who passed the quiz and then
    // abandoned would fall from the $1 tier to $0 -- a payment change nobody
    // asked for.
    return [Consent, AIAgreement, Introduction, Quiz];
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
    // AIDisclosure precedes the demographic survey wherever a participant
    // produced data. Asked BEFORE the survey rather than buried inside it, so it
    // reads as a separate question about data usability rather than one more
    // demographic field -- and so it is still answered if they abandon the
    // longer survey partway.
    if (player.get("finishedTraining")) {
      return [Posttest, AIDisclosure, ExitSurvey];
    }
    // Everything below the post-test is one decision, made in tiers.js so that
    // this file, Finished.jsx and 00_preprocessing.R cannot disagree about which
    // tier someone is in -- they used to, and participants got contradictory
    // instructions about whether to submit or return.
    switch (exitTier(player)) {
      case "lobby":
        // Either no partner ever arrived, or they held a slot in a game that ran
        // and contributed nothing. No completion code either way.
        return [
          (props) => (
            <LobbyExitSurvey {...props} noPartner={!game} />
          ),
        ];
      case "no_lobby":
      case "no_intro":
        return [NoGameSurvey];
      default:
        // Had a game and contributed, but it ended before training finished:
        // inactivity timeout, or a partner who dropped. Paid in full -- and
        // their partial data still needs an AI disclosure to be usable.
        return [AIDisclosure, IncompleteExitSurvey];
    }
  }

  return (
    <EmpiricaParticipant url={url} ns={playerKey} modeFunc={EmpiricaClassic}>
      <div className="h-screen relative">
        <EmpiricaMenu position="bottom-left" />
        <div className="h-full overflow-auto">
          <EmpiricaContext playerCreate={MyPlayerForm} introSteps={introSteps}
          exitSteps={exitSteps} finished={Finished}>
            <Game />
          </EmpiricaContext>
        </div>
      </div>
    </EmpiricaParticipant>
  );
}
