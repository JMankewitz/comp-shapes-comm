import {Chat, useGame, useRound, usePlayer} from "@empirica/core/player/classic/react";

import React, { useEffect } from "react";
import { PhaseCard } from "./components/PhaseCard";
import { Profile } from "./Profile";
import { Task } from "./Task";
import { Describe } from "./Describe";

// The game-start bell stays at full volume -- it fires once and is the cue that
// the session has begun. The between-round chime fires on every one of the 48
// training trials, where full volume is jarring rather than informative.
const ROUND_SOUND_VOLUME = 0.2;

const roundSound = new Audio("round-sound.mp3");
roundSound.volume = ROUND_SOUND_VOLUME;

const gameSound = new Audio("bell.mp3");
gameSound.volume = 1.0;

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

  // Pre/post are solo free-description phases: no partner interaction at all.
  // The Chat pane is UNMOUNTED rather than hidden, so no chat attribute is ever
  // created on those rounds and nothing can be typed to a partner (S4.3).
  // Only the PRE-test runs inside the game. The post-test moved to exitSteps
  // (intro-exit/Posttest.jsx) so a participant who finishes first can leave
  // rather than waiting on their partner.
  const phase = round?.get("phase");
  if (phase === "pretest") {
    // Player-scoped, not local state: a refresh mid-phase should resume the task,
    // not make them click through the intro again.
    const startPretest = () => player.set("pretestStarted", true);
    if (!player.get("pretestStarted")) {
      return (
        <div className="h-full w-full flex flex-col">
          <Profile />
          <div className="h-full flex items-center justify-center overflow-auto">
            <PhaseCard
              eyebrow="Part 1 of 3"
              title="Describing shapes on your own"
              buttonLabel="Start Part 1"
              onContinue={startPretest}
            >
              <p>
                You will see a series of shapes, one at a time. For each one, type a
                short description so that another person could pick it out.
              </p>
              <p>
                There is <b>no partner</b> in this part and <b>no score</b> — just
                describe each shape in your own words.
              </p>
            </PhaseCard>
          </div>
        </div>
      );
    }
    return (
      <div className="h-full w-full flex flex-col">
        <Profile />
        <div className="h-full flex items-center justify-center overflow-auto">
          <Describe
            phase="pretest"
            secondsPerItem={game?.get("describeSecondsPerItem") || 60}
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
