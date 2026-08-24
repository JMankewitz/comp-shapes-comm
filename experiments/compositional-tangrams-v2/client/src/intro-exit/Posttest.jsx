import { usePlayer } from "@empirica/core/player/classic/react";
import React from "react";
import { Describe } from "../Describe";
import { PhaseCard } from "../components/PhaseCard";

// Post-test as an EXIT STEP rather than a game round.
//
// The post-test is the last thing a participant does and nothing after it
// depends on their partner, so there is no reason to hold a fast finisher while
// the slower one works. As a round it paced to max(A, B); here each participant
// walks their own list and goes straight to the exit survey.
//
// Everything it needs is on the player scope, written at game start:
// `posttestItems` (already shuffled per player) and `rotation`. Responses are
// appended to `posttestResponses` exactly as before, so the export is unchanged.
export function Posttest({ next }) {
  const player = usePlayer();

  // A dyad that never finished training has nothing to post-test on. App.jsx
  // gates on this too; the guard here keeps the component safe on its own.
  if (!player.get("finishedTraining")) {
    next();
    return null;
  }

  // The game has just ended, so without this the participant jumps straight from
  // the last training round into a different task with no warning.
  if (!player.get("posttestStarted")) {
    return (
      <div className="h-full w-full flex items-center justify-center overflow-auto">
        <PhaseCard
          eyebrow="Part 3 of 3"
          title="The matching game is complete"
          buttonLabel="Start Part 3"
          onContinue={() => player.set("posttestStarted", true)}
        >
          <p>
            Nice work — that is the end of the game with your partner. Your bonus
            from that part has been recorded.
          </p>
          <p>
            For this last part you will describe shapes on your own again, exactly
            as you did in Part 1. Same instructions: one shape at a time, describe
            it so another person could pick it out.
          </p>
          <p className="text-sm text-gray-500">
            A short survey follows.
          </p>
        </PhaseCard>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex items-center justify-center overflow-auto">
      <Describe
        phase="posttest"
        secondsPerItem={player.get("describeSecondsPerItem") || 60}
        onComplete={next}
        doneMessage="That is the last shape. Continuing to a short final survey."
      />
    </div>
  );
}
