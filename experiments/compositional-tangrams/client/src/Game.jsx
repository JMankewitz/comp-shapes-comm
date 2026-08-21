import {Chat, useGame, useRound, usePlayer} from "@empirica/core/player/classic/react";

import React, { useEffect } from "react";
import { Profile } from "./Profile";
import { Task } from "./Task";
import { Describe } from "./Describe";

const roundSound = new Audio("round-sound.mp3");
const gameSound = new Audio("bell.mp3");

export function Game() {
  const game = useGame();
  const round = useRound();
  const player = usePlayer();

  useEffect(() => {
    if (game.get("justStarted")) {
      gameSound.play().catch(e => console.warn("Error playing game sound:", e));
      game.set("justStarted", false);
    }
  }, [game.get("justStarted")]);

  useEffect(() => {
    if (round?.get("justStarted")) {
      roundSound.play().catch(e => console.warn("Error playing round sound:", e));
      round.set("justStarted", false);
    }
  }, [round?.get("justStarted")]);

  //if (game.get("justStarted")) {
  //  gameSound.play().catch(e => console.warn("Error playing game sound:", e));
  //  game.set("justStarted", false);
 // } else {
  //  if (round.get("justStarted")) {
  //  roundSound.play().catch(e => console.warn("Error playing round sound:", e));
  //  round.set("justStarted", false);}
 // }

  // Pre/post are solo free-description phases: no partner interaction at all.
  // The Chat pane is UNMOUNTED rather than hidden, so no chat attribute is ever
  // created on those rounds and nothing can be typed to a partner (S4.3).
  // Only the PRE-test runs inside the game. The post-test moved to exitSteps
  // (intro-exit/Posttest.jsx) so a participant who finishes first can leave
  // rather than waiting on their partner.
  const phase = round?.get("phase");
  if (phase === "pretest") {
    return (
      <div className="h-full w-full flex flex-col">
        <Profile />
        <div className="h-full flex items-center justify-center overflow-auto">
          <Describe
            phase="pretest"
            onComplete={() => player.stage.set("submit", true)}
            doneMessage="Waiting for your partner to finish theirs. The game will begin automatically."
          />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex">
      <div className="h-full w-full flex flex-col">
        <Profile />
        <div className="h-full flex items-center justify-center">
          <Task />
        </div>
      </div>

      <div className="h-full w-128 border-l flex justify-center items-center">
        <Chat scope={round} player={player} attribute="chat" 
        />
      </div>
    </div>
  );
}
